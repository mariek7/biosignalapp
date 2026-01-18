from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
import asyncio
import os
from dotenv import load_dotenv
from serial.tools import list_ports
from core.device import BITalino
from core.mock_device import MockBITalino

load_dotenv()

logging.basicConfig( # configure logging
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

app = FastAPI()
device_locks: dict[str, asyncio.Lock] = {} # Per-device asyncio locks to prevent concurrent access to same BITalino

class BITalinoRequest(BaseModel):
    macAddress: str
    samplingRate: int
    recordingTime: int
    # optional - request specific channels ["A1","A2"] and sensor types {"A1":"ACCBIT"}
    channels: list[str] | None = None
    channel_types: dict | None = None

# GET from /bitalino-get/?macAddress=[mac-address]&samplingRate=[sr]&recordingTime=[rt]
@app.get("/bitalino-get/")
async def bitalino_data(macAdd: str, samplingRate: int, recordingTime: int):
    """Return raw samples acquired from BITalino device as JSON.
    """
    
    use_mock = os.getenv('USE_MOCK_DEVICE', 'false').lower() == 'true' # check if mock mode is enabled
    DeviceClass = MockBITalino if use_mock else BITalino
    
    device = DeviceClass(macAddress=macAdd, timeout=10)
    lock = device_locks.setdefault(macAdd, asyncio.Lock())
    
    async with lock:
        try:
            max_attempts = 3 # retry loop for transient device I/O errors
            attempt = 0
            while True: 
                try:
                    attempt += 1
                    logging.debug("Opening device %s (attempt %d/%d)", macAdd, attempt, max_attempts)
                    device.open(macAddress=macAdd, SamplingRate=samplingRate)
                    device.start()
                    nSamples = samplingRate * recordingTime  # total samples to read based on time and rate
                    data = device.read(nSamples=nSamples, timeout=10) # read data for given time
                    logging.debug("Successfully acquired %d samples from %s", len(data), macAdd)
                    break
                    
                except Exception as e:
                    # for transient I/O error, attempt to retry after short backoff
                    try:
                        err_no = getattr(e, 'errno', None)
                    except Exception:
                        err_no = None
                    logging.warning("Device operation failed on attempt %d/%d: %s (errno=%s)", attempt, max_attempts, repr(e), err_no)
                    
                    # if EIO (errno 5) or other transient socket errors, try to close/reopen and retry
                    if attempt < max_attempts and (isinstance(e, OSError) and err_no in (5, 11, None) or isinstance(e, TimeoutError)):
                        import time
                        logging.info("Retrying device operation after short backoff...")
                        try:
                            device.close()
                        except Exception:
                            pass
                        time.sleep(0.2 * attempt)
                        continue
                    
                    # else map to clearer HTTP codes and re-raise
                    if isinstance(e, OSError) and err_no == 5:
                        logging.exception("Device EIO final failure")
                        raise HTTPException(status_code=503, detail=f"Device write failed (EIO): {e}")
                    if isinstance(e, TimeoutError):
                        logging.exception("Device timeout final failure")
                        raise HTTPException(status_code=504, detail=str(e))
                    if isinstance(e, OSError) and err_no == 16:
                        logging.exception("Device busy")
                        raise HTTPException(status_code=409, detail=str(e))
                    
                    # BT timeout
                    try:
                        import bluetooth as _bt
                        if isinstance(e, _bt.btcommon.BluetoothError) and 'timed out' in str(e).lower():
                            raise HTTPException(status_code=504, detail=str(e))
                    except HTTPException:
                        raise
                    except Exception:
                        pass
                    
                    logging.exception("Device operation final failure")
                    raise HTTPException(status_code=500, detail=str(e))

            return {
                "macAddress": macAdd,
                "samplingRate": samplingRate,
                "recordingTime": recordingTime,
                "data": data.tolist()  # Convert NumPy array to list for JSON serialization
                # TODO: check for unnecessary data type conversions
            }
        finally:
            try:
                device.stop()
            except Exception:
                pass
            try:
                device.close()
            except Exception:
                pass


@app.get("/bitalino-health/")
async def bitalino_health(macAdd: str):
    """Small health check for BITalino device. Returns whether device/address appears present.
    """
    try:
        # fast check,  serial ports, e.g., /dev/rfcomm0 or attached serial devices
        ports = [p.device for p in list_ports.comports()]
        if macAdd in ports:
            return {"macAddress": macAdd, "found": True}

        # otherwise try short BT discovery in background thread to avoid blocking
        device = BITalino(macAddress=macAdd, timeout=10)
        found = False
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(device.find, False)
                try:
                    devs = future.result(timeout=3)  # short timeout (seconds)
                except concurrent.futures.TimeoutError:
                    logging.warning("Bluetooth discovery timed out for %s", macAdd)
                    raise HTTPException(status_code=504, detail="Bluetooth discovery timed out")
        except HTTPException:
            raise
        except Exception:
            logging.exception("Bluetooth discovery failed")
            devs = []

        if isinstance(devs, list):
            for d in devs:
                if isinstance(d, tuple) and len(d) >= 1:
                    addr = d[0]
                else:
                    addr = d
                if addr == macAdd:
                    found = True
                    break

        return {"macAddress": macAdd, "found": found}
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Health check error")
        raise HTTPException(status_code=500, detail=str(e))

# POST to get data from /bitalino-data/
@app.post("/bitalino-data/")
async def get_bitalino_data(request: BITalinoRequest):
    """Return raw samples acquired from the BITalino device as JSON.
    """
    device = BITalino(macAddress=request.macAddress, timeout=10)
    lock = device_locks.setdefault(request.macAddress, asyncio.Lock())
    device_opened = False  # track whether device was successfully opened

    async with lock:
        try:
            # Retry loop for I/O errors
            max_attempts = 3
            attempt = 0
            while True:
                try:
                    attempt += 1
                    logging.debug("Opening device %s (attempt %d/%d)", request.macAddress, attempt, max_attempts)
                    device.open(request.macAddress, request.samplingRate)
                    device_opened = True  # mark as opened successfully
                    logging.info("BITalino: %s", device)
                    device.start()
                    nSamples = int(request.samplingRate * request.recordingTime)
                    # increase read timeout
                    dataAcquired = device.read(nSamples, timeout=10)
                    # build column names for the rows present in dataAcquired
                    column_names = ['seqN', 'D0', 'D1', 'D2', 'D3', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6'][:dataAcquired.shape[0]]
                    break
                except Exception as e:
                    # If a transient I/O error, attempt to retry after short backoff
                    try:
                        err_no = getattr(e, 'errno', None)
                    except Exception:
                        err_no = None
                    logging.warning("Device operation failed on attempt %d/%d: %s (errno=%s)", attempt, max_attempts, repr(e), err_no)
                    # If EIO (errno 5) or other transient socket errors, try to close/reopen and retry
                    if attempt < max_attempts and (isinstance(e, OSError) and err_no in (5, 11, None) or isinstance(e, TimeoutError)):
                        import time
                        logging.info("Retrying device operation after short backoff...")
                        try:
                            device.close()
                        except Exception:
                            pass
                        time.sleep(0.2 * attempt)
                        continue
                    # else map to clearer HTTP codes and re-raise
                    if isinstance(e, OSError) and err_no == 5:
                        logging.exception("Device EIO final failure")
                        raise HTTPException(status_code=503, detail=f"Device write failed (EIO): {e}")
                    if isinstance(e, TimeoutError):
                        logging.exception("Device timeout final failure")
                        raise HTTPException(status_code=504, detail=str(e))
                    logging.exception("Device operation final failure")
                    raise HTTPException(status_code=500, detail=str(e))

            # read all available data from device, filter channles later
            requested = getattr(request, 'channels', None)
            logging.debug("channels from request: %s (type: %s)", requested, type(requested))
            def _normalize_label(lbl: str) -> str:
                if not isinstance(lbl, str):
                    return lbl
                s = lbl.strip().upper()
                if s.startswith('A') and s[1:].isdigit(): # analog labels A1..A6
                    return s
                # TODO: check digital channels mapping
                if s.startswith('D') and s[1:].isdigit(): # digital labels, are there D-starting labels?
                    return 'D' + str(int(s[1:]))
                if s.isdigit(): # numeric or zero-padded like '01' -> map to Dn
                    return 'D' + str(int(s))
                if s.startswith('I') and s[1:].isdigit(): # I1 or 01 prefix variants -> Dn
                    return 'D' + str(int(s[1:]))
                return s

            if requested:
                requested_norm = [_normalize_label(l) for l in requested]
            else:
                requested_norm = None
                requested = None

            # column names based on dataAcquired rows
            full_column_names = ['seqN', 'D0', 'D1', 'D2', 'D3', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6'][:dataAcquired.shape[0]]

            # If requested was provided, filter columns to the requested set (preserve order in requested)
            if requested_norm:
                logging.debug("Filtering: requested_norm=%s, full_column_names=%s", requested_norm, full_column_names)
                # keep seqN and any requested that exist in full_column_names
                selected = ['seqN'] + [c for c in requested_norm if c in full_column_names]
                logging.debug("Selected columns: %s", selected)
                
                try: # compute row indices to keep
                    indices = [full_column_names.index(c) for c in selected]
                    logging.debug("Row indices to extract: %s", indices)
                    sub = dataAcquired[indices, :] # subset rows from dataAcquired
                    column_names = selected
                except (ValueError, IndexError) as e:
                    logging.warning("Failed to filter to requested columns %s: %s. Using all columns.", requested_norm, e)
                    sub = dataAcquired
                    column_names = full_column_names
            else:
                sub = dataAcquired
                column_names = full_column_names

            # Send samples × channels (rows = samples) and include explicit columns metadata and channel types
            data_samples = sub.astype(float).T.tolist()

            # Normalize and echo back channel_types (map keys to normalized column names)
            channel_types_out = {}
            if getattr(request, 'channel_types', None):
                # normalize incoming keys and map them to normalized columns
                for k, v in request.channel_types.items():
                    nk = k.strip().upper()
                    if nk.isdigit():
                        nk = 'D' + str(int(nk))
                    elif nk.startswith('I') and nk[1:].isdigit():
                        nk = 'D' + str(int(nk[1:]))
                    elif nk.startswith('D') and nk[1:].isdigit():
                        nk = 'D' + str(int(nk[1:]))
                    # only include if normalized key is in returned columns
                    if nk in column_names:
                        channel_types_out[nk] = v
            return {"data": data_samples, "columns": column_names, "channel_types": channel_types_out}
        except Exception as e:
            logging.exception("Error acquiring BITalino data")
            if isinstance(e, OSError) and getattr(e, 'errno', None) == 5:
                # EIO - Input/output error (e.g device disconnected, low-level rfcomm problem)
                raise HTTPException(status_code=503, detail=f"Device write failed (EIO): {e}")
            if isinstance(e, TimeoutError):
                raise HTTPException(status_code=504, detail=str(e))
            # Bluetooth timeouts already handled in the GET handler, fallback to 500 for other errors
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            if device_opened:  # only stop() if device was successfully opened
                try:
                    device.stop()
                except Exception:
                    pass
            try:
                device.close()
            except Exception:
                pass
    

