import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import json
import time
from datetime import datetime
from .signal_type import signal_types, eeg_transfer, eda_transfer, ecg_transfer, emg_transfer, acc_transfer # import transfer functions

from dotenv import load_dotenv
import os


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format='%(asctime)s %(levelname)s: %(message)s')


def create_requests_session(retries: int = 3, backoff_factor: float = 0.3) -> requests.Session:
    session = requests.Session()
    retry = Retry(total=retries, backoff_factor=backoff_factor, status_forcelist=(500, 502, 504))
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def parse_acquisition_response(response_text: str) -> pd.DataFrame:
    """Parse BITalino-style JSON response into dataframe.
    """
    payload = json.loads(response_text)
    if "error" in payload:
        raise ValueError(f"API error: {payload.get('error')} - {payload.get('detail')}")

    data_got = payload.get("data", [])
    if not data_got:
        raise ValueError("No 'data' field in response or it's empty.")

    provided_columns = payload.get("columns") # prefer explicit columns metadata when available

    # ensure numeric dtype early to avoid ambiguous numpy scalar types later
    try:
        arr = np.asarray(data_got, dtype=float)
    except Exception as e:
        raise ValueError(f"Failed to convert data to numeric array: {e}")

    if arr.ndim != 2:
        raise ValueError(f"Unexpected data shape from device: {arr.shape}")

    default_columns = ['seqN', 'D0', 'D1', 'D2', 'D3', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6']

    if provided_columns:
        columns = list(provided_columns)
        # Ensure arr is samples × channels; if the server sent channels × samples, transpose
        if arr.shape[1] == len(columns):
            pass
        elif arr.shape[0] == len(columns):
            arr = arr.T
        else:
            # Fallback, trim/extend columns to match the array width
            if arr.shape[1] < len(columns):
                columns = columns[:arr.shape[1]]
            elif arr.shape[1] > len(columns):
                # If there are more columns than names, generate generic names
                columns = columns + [f'X{i}' for i in range(len(columns), arr.shape[1])]
    else:
        # Infer orientation, if rows <-- default columns it's likely channels × samples
        if arr.shape[0] <= len(default_columns) and arr.shape[1] > arr.shape[0]:
            arr = arr.T
        columns = default_columns[:arr.shape[1]]

    try:
        df = pd.DataFrame(arr, columns=columns)
    except Exception as e:
        raise ValueError(f"Error creating DataFrame: {e}")

    # capture optional channel_types metadata
    channel_types = payload.get('channel_types')
    def _normalize_label(lbl: str) -> str:
        if not isinstance(lbl, str):
            return lbl
        s = lbl.strip().upper()
        if s.startswith('A') and s[1:].isdigit():
            return s
        if s.startswith('D') and s[1:].isdigit():
            return 'D' + str(int(s[1:]))
        if s.isdigit():
            return 'D' + str(int(s))
        if s.startswith('I') and s[1:].isdigit():
            return 'D' + str(int(s[1:]))
        return s

    if isinstance(channel_types, dict):
        # Normalize keys to match columns present
        normalized = {_normalize_label(k): v for k, v in channel_types.items()}
        df.attrs['channel_types'] = {k: normalized[k] for k in normalized if k in df.columns}
    elif isinstance(channel_types, list):
        # If list provided, align with columns
        df.attrs['channel_types'] = {col: channel_types[i] for i, col in enumerate(df.columns) if i < len(channel_types)}
    else:
        df.attrs['channel_types'] = {}

    return df


def write_to_file(path: str, mac: str, sampling_rate: int, times: list, data: dict, channel_labels: list, device_name: str = None, header_key: str = None, sensor_types: dict | None = None):
    """Write a text data file with a JSON-style header and tab-separated rows.
    The header contains basic metadata (device name, sampling rate, channel labels).
    """
    now = datetime.now()
    date_str = f"{now.year}-{now.month}-{now.day}"
    time_str = now.strftime("%H:%M:%S.%f")[:-3]

    device_name = device_name or mac
    header_key = header_key or device_name

    if sensor_types: # derive sensor list in the same order as channel_labels
        sensor_list = [sensor_types.get(ch, ch) for ch in channel_labels]
    else:
        sensor_list = channel_labels
    # TODO: check what header meta data is needed by BITalino specs
    meta = {
        header_key: {
            "position": 0,
            "device": device_name,
            "device name": device_name,
            "device connection": f"BTH{mac}",
            "sampling rate": sampling_rate,
            "resolution": [None] * (len(channel_labels) + 5),
            "firmware version": None,
            "mode": 0,
            "sync interval": 2,
            "date": date_str,
            "time": time_str,
            "channels": list(range(1, len(channel_labels) + 1)),
            "sensor": sensor_list,
            "label": channel_labels,
            "column": ["Time"] + channel_labels,
            "special": [{}],
            "digital IO": [0, 0, 1, 1],
            "convertedValues": 1
        }
    }
    # write header line and tab-separeted data lines
    with open(path, 'w', newline='') as fh:
        fh.write('# ' + json.dumps(meta) + "\n")
        fh.write('# EndOfHeader\n')
        # rows: time then channel values
        n = len(times)
        for i in range(n):
            row = [f"{times[i]:.6f}"]
            for ch in channel_labels:
                vals = data.get(ch, [])
                v = vals[i] if i < len(vals) else ''
                try:
                    row.append(f"{float(v):.6f}")
                except Exception:
                    row.append(str(v))
            fh.write('\t'.join(row) + "\n")
    logging.info('Saved text data file to %s', path)


def realtime_acquisition(phase: str = None, channels_env: str = None, verbose: bool = False, device_name: str = None, header_key: str = None) -> str:

    load_dotenv()
    date_and_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
    mac_address = os.getenv('MAC_ADDRESS')

    # initialize logging
    setup_logging(verbose)

    # channels selection
    env_channels = channels_env or os.getenv('CHANNELS', 'A1')
    channels_selected = [c.strip() for c in env_channels.split(',') if c.strip()]

    signal_type_key = os.getenv('signal_type','None') #  ecg|eda|eeg|emg|acc|raw, if none then raw
    logging.info('Signal type: %s', signal_type_key)

    signal = signal_types.get(signal_type_key, signal_types['None'])
    sampling_rate = signal.sampling_rate
    signal_unit= signal.unit
    transfer_func = signal.transfer_function

    # mapping from sensor string to transfer function
    SENSOR_TRANSFER = {
        'RAW': lambda x: x,
        'ECGBIT': ecg_transfer,
        'EDABIT': eda_transfer,
        'EEGBIT': eeg_transfer,
        'EMGBIT': emg_transfer,
        'ACCBIT': acc_transfer,
        'ACCBITREV': acc_transfer,
    }

    logging.info("Timestamp: %s", date_and_time)
    logging.info("MAC Address: %s", mac_address)
    logging.info("Signal: %s (sampling rate %s, unit %s)", signal.name, sampling_rate, signal.unit)
    logging.info("Transfer function: %s", transfer_func.__name__)
   
    session = create_requests_session()  # create a requests session with retries
    request_timeout = float(os.getenv('REQUEST_TIMEOUT', '10')) # request timeout, configurable from env var REQUEST_TIMEOUT
    logging.debug('Using request timeout: %s seconds', request_timeout)

    # failure config
    consecutive_failures = 0
    max_failures = int(os.getenv('MAX_CONSECUTIVE_FAILURES', '10'))
    backoff_base = float(os.getenv('BACKOFF_BASE', '0.25'))
    max_backoff = float(os.getenv('MAX_BACKOFF', '8'))

    def record_failure(reason: str):
        nonlocal consecutive_failures, stop
        consecutive_failures += 1
        backoff = min(max_backoff, backoff_base * (2 ** (consecutive_failures - 1)))
        logging.warning('Frame failure %d/%d: %s; backing off %.2fs', consecutive_failures, max_failures, reason, backoff)
        try:
            time.sleep(backoff)
        except Exception:
            pass
        if consecutive_failures >= max_failures:
            logging.error('Max consecutive failures reached (%d) - stopping animation', max_failures)
            stop = True
            try:
                anim.event_source.stop()
            except Exception:
                pass

    # optional health check before starting, env CHECK_DEVICE_HEALTH to 0 to disable
    if mac_address and os.getenv('CHECK_DEVICE_HEALTH', '1').lower() in ('1', 'true', 'yes'):
        try:
            hresp = session.get(f"http://localhost:8000/bitalino-health/?macAddress={mac_address}", timeout=request_timeout)
            hresp.raise_for_status()
            j = hresp.json()
            if not j.get('found', False):
                logging.warning('Device health check reports device not found: %s', mac_address)
                if os.getenv('ABORT_ON_HEALTH_FAIL', '0') in ('1', 'true', 'yes'):
                    logging.error('Aborting due to failed device health check')
                    return filename
        except requests.RequestException as e:
            logging.warning('Device health check failed: %s', e)
            logging.warning('Make sure the FastAPI server is running! Start it with: python3 -m uvicorn api.server:app --host 127.0.0.1 --port 8000')
            logging.warning('or use the startup script: bash start_gui.sh <mac-address>')
            
            # If API server is not responding on first health check, give a moment to start
            if 'Connection refused' in str(e) or 'failed to establish' in str(e).lower():
                logging.warning('API server appears to not be running. Retrying in 3 seconds...')
                time.sleep(3)
                try:
                    hresp = session.get(f"http://localhost:8000/bitalino-health/?macAddress={mac_address}", timeout=request_timeout)
                    hresp.raise_for_status()
                    logging.info('API server is now responding')
                except requests.RequestException as e2:
                    logging.error('API server still not responding: %s', e2)
                    logging.error('Cannot proceed without API server. Exiting.')
                    raise RuntimeError("API server at http://localhost:8000 is not responding") from e2


    # per-channel data buffers and global time buffer
    data_buffer = {ch: [] for ch in channels_selected}
    time_buffer = []
    all_data = {ch: [] for ch in channels_selected}  # for saving to file per-channel
    all_time = []
    t = 0
    dt =1.0/sampling_rate

    fig, ax = plt.subplots(figsize=(10, 5))
    # multichannel plotting
    lines = []
    for ch in channels_selected:
        ln, = ax.plot([], [], lw=1, label=ch)
        lines.append(ln)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel(signal_unit)
    ax.set_ylim(signal.ylim) # from core/signal_type.py
    if len(channels_selected) > 1:
        ax.legend()

    window_seconds = 2

    stop = False
    current_channel_types = {}

    def on_key(event):
        nonlocal stop
        if event.key == ' ':  # spacebar pressed
            logging.info("Stopping --")
            stop = True


    def animate(frame):
        nonlocal stop, consecutive_failures, current_channel_types
        try:
            try:
                #response = session.get(f"http://localhost:8000/bitalino-get/?macAddress={mac_address}&samplingRate={sampling_rate}&recordingTime=1", timeout=request_timeout)
                response = session.post("http://localhost:8000/bitalino-data/", 
                       json={
                           "macAddress": mac_address,
                           "samplingRate": sampling_rate, 
                           "recordingTime": 1.0,
                           "channels": channels_selected if channels_selected else None
                       })
                response.raise_for_status()
            except requests.exceptions.ReadTimeout:
                record_failure(f"request timeout after {request_timeout}s")
                return
            except requests.exceptions.RequestException as re:
                record_failure(f"request error: {re}")
                return

            try:
                all_df = parse_acquisition_response(response.text)
            except ValueError as e:
                record_failure(f"parse error: {e}; server response: {(response.text[:1000] if response is not None else '<no-response>')}" )
                return

            logging.debug('Parsed data shape: %s', all_df.shape)
            logging.debug('Parsed columns: %s', list(all_df.columns))
            available = [c for c in channels_selected if c in all_df.columns]
            if not available:
                logging.warning('None of requested channels present in data: %s', channels_selected)
                return
            logging.debug(all_df[available].head().to_string())

            current_channel_types = getattr(all_df, 'attrs', {}).get('channel_types', {}) # capture per-channel types

            # for each selected channel extract data, apply transfer function and update buffers
            n_samples = None
            times = None
            for ch_idx, ch in enumerate(available):
                series = all_df[ch].values
                # pick per-channel transfer function
                channel_types = getattr(all_df, 'attrs', {}).get('channel_types', {})
                sensor = channel_types.get(ch)
                if sensor:
                    tf = SENSOR_TRANSFER.get(sensor.upper(), transfer_func)
                else:
                    tf = transfer_func
                transferred = tf(series)

                if n_samples is None:
                    n_samples = len(transferred)
                    nonlocal t
                    times = np.arange(t, t + n_samples * dt, dt)
                    t += n_samples * dt

                # convert transferred NumPy array to native Python floats to avoid numpy scalar issues later
                vals = transferred.tolist() if hasattr(transferred, 'tolist') else [float(x) for x in transferred]
                # save per-channel data
                all_data[ch].extend(vals)

                # update rolling buffers per-channel
                data_buffer[ch].extend(vals)
                logging.debug('Channel %s: added %d samples', ch, len(vals))

            if n_samples is None or times is None: # nothing to plot
                return tuple(lines)

            consecutive_failures = 0 # reset consecutive failures on success

            all_time.extend(times)

            # update common time buffer
            time_buffer.extend(times)
            if len(time_buffer) > sampling_rate * window_seconds:
                time_buffer[:] = time_buffer[-sampling_rate*window_seconds:]

            # trim per-channel buffers to window
            for ch in channels_selected:
                if len(data_buffer[ch]) > sampling_rate * window_seconds:
                    data_buffer[ch][:] = data_buffer[ch][-sampling_rate*window_seconds:]

            # update each lines data
            for idx, ch in enumerate(channels_selected):
                lines[idx].set_data(time_buffer, data_buffer[ch])

            # make sure axes show the new data
            # compute y-range across all channels to keep consistent view
            combined = np.hstack([np.asarray(data_buffer[ch]) for ch in channels_selected if len(data_buffer[ch])>0]) if channels_selected else np.array([])
            if len(time_buffer) > 0 and combined.size > 0:
                # x limits, show current window
                x_min = time_buffer[0]
                x_max = time_buffer[-1]
                ax.set_xlim(x_min, x_max)

                # y limits, add a small margin so points are visible
                y_min = float(np.min(combined))
                y_max = float(np.max(combined))
                if y_min == y_max:
                    delta = abs(y_min) * 0.1 if y_min != 0 else 1.0
                else:
                    delta = (y_max - y_min) * 0.1
                ax.set_ylim(y_min - delta, y_max + delta)

            ax.relim()
            ax.autoscale_view()

            if stop:
                anim.event_source.stop()  # end animation loop
            return tuple(lines)
        except Exception as e:
            logging.exception("Error fetching or processing data")
            logging.debug("Channels selected: %s", channels_selected)
            try:
                logging.debug("all_df columns: %s", list(all_df.columns))
            except Exception:
                pass
            record_failure(str(e))
            return

    fig.canvas.mpl_connect('key_press_event', on_key)
    anim = animation.FuncAnimation(fig, animate, interval=200, cache_frame_data=False)
    plt.show()

    filename = f'data_recording_{date_and_time}_{signal.name}'

    # prepare df for saving: time + one column per channel
    save_dict = {'Time (s)': all_time}
    for ch in channels_selected:
        save_dict[ch] = all_data.get(ch, [])

    out_format = os.getenv('SAVE_FORMAT', 'tsv') # tab-separated or comma-separated
    if out_format == 'tsv':
        out_path = f'data/recordings/{filename}_{phase}.txt'
        # pick device name and header key from args or environment, if any TODO: check if these are used
        _device_name = device_name or os.getenv('DEVICE_NAME') 
        _header_key = header_key or os.getenv('HEADER_KEY')
        write_to_file(out_path, mac_address or 'unknown', sampling_rate, all_time, all_data, channels_selected, device_name=_device_name, header_key=_header_key, sensor_types=current_channel_types)
    else:
        out_df = pd.DataFrame(save_dict)
        out_path = f'data/recordings/{filename}_{phase}.csv'
        out_df.to_csv(out_path, index=False)
        logging.info('Saved recording to %s', out_path)

    return filename