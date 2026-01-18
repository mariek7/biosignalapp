# App structure and user guide

## Overview
This is a Python application for acquiring, processing and visualizing biosignals from BITalino devices via Bluetooth. It provides both a **GUI** (PyQt5) and **command-line** interfaces.


## Quick start

### 1. Install dependencies

Install:
```bash
pip install -r requirements.txt
```

Create `.env` file (optional):
```dotenv
# rfcomm device path
MAC_ADDRESS=/dev/rfcomm0
DEVICE_MAC=<MAC_ADDRESS>
```

### 2. Quick start options

**Option A: GUI with API**
```bash
./start_gui.sh
```
Starts both FastAPI server and GUI

**Option B: Manual (separate terminals)**
```bash
# Terminal 1: Start API server
python3 -m uvicorn api.server:app --host 127.0.0.1 --port 8000

# Terminal 2: Launch GUI
python3 main.py
```

**TBD: Terminal acquisition**

---

## Folder structure

```
biosignals/
├── api/                   # FastAPI BACKEND
│   └── server.py          # HTTP endpoints for device communication
|
├── core/                  # CORE DEVICE AND DATA HANDLING
│   ├── device.py          # BITalino
│   ├── signal_type.py     # Signal definitions and transfer functions
│   └── file_io.py         # Data acquisition and real-time plotting
|
├── ui/                    # USER INTERFACE
│   └── main_window.py     # PyQt5 GUI application
|
├── data/
│   └── recordings/        # LOCATION OF SAVED DATA FILES
|
├── requirements.txt       
├── main.py                # Entry point for GUI
└── start_gui.sh           # Automated startup script
```

---


## API (`api/`)

### `server.py` - FastAPI Backend
**Purpose:** HTTP REST API for device communication

**Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/bitalino-health/` | GET | Lightweight device discovery |
| `/bitalino-data/` | POST | Acquire data with channel selection |

**Example**
```bash
# Health check
curl "http://127.0.0.1:8000/bitalino-health/?macAdd=<MAC_ADDRESS>"

# Get data (POST)
curl -X POST http://127.0.0.1:8000/bitalino-data/ \
  -H "Content-Type: application/json" \
  -d '{"macAddress":"<MAC_ADDRESS>","channels":"A1,D1","nsamples":100}'
```

---

## Core (`core/`)

### `device.py` - BITalino
**Purpose:**  Bluetooth/serial communication with BITalino device

**Methods:**
- `find()` - Discover available BITalino devices via Bluetooth
- `open()` - Open a connection to a BITalino device over Bluetooth or serial
- `start()` - Start acquisition on specified channels
- `stop()` - Stop acquisition
- `close()` - Close connection and cleanup
- `write()` - Write a single control byte to the device. (Helps recover from occasional Bluetooth or serial hiccups without requiring a full reconnect.)
- `read()` - Read data from device
- `decode()` - Return decoded data

---

### `signal_type.py` - Signal Definitions
**Purpose:** Signal types and their properties (unit, range, sampling rate, transfer functions for each type)

**Signals:**
- `ECG` - Electrocardiogram (mV, 1000 Hz)
- `EEG` - Electroencephalogram (μV, 100 Hz)
- `EMG` - Electromyography (mV, 1000 Hz)
- `ACC` - Accelerometer (g, 100 Hz)
- `EDA` - Electrodermal Activity (μS, 4 Hz)
- `None` - Raw data (100 Hz)

---

### `file_io.py` - Data acquisition and I/O
**Purpose:** Real-time multi-channel data acquisition and plotting, and file saving with time stamps.

**Methods:**
- `setup_logging()`
- `create_requests_session()`
- `parse_acquisition_response()` - Parse API response
- `write_to_file()` - Save data to file
- `realtime_acquisition()` - Main acquisition loop

---

## UI (`ui/`)

### `main_window.py` - PyQt5 GUI
Graphical interface for data acquisition and playback

**Features:**
- Real-time signal plotting with embedded matplotlib
- Channel and signal type selection
- Acquisition and data playback control

**Methods:**
- `mode_changed()` - Acquire or playback mode
- `selection_changed()` - Called whenever channel selection or plot mode changes.
- `get_selected_channels()` - Return channels and types
- `is_channel_hidden()` - Check if channel is hidden for button state
- `toggle_channel_plot()` - Hide/show channel plot and rebuild to resize.
- `toggle_all_plots_visibility()` - Hide/show all plots with one button
- `init_data()` - Initialize for data acquisition
- `load_file()` - Load data file to play
- `update_playback()`
- `toggle_play_pause()`
- `update_button_states()`
- `hide_show_plot_widget()`
- `start_plotting()`
- `stop_plotting_and_save()`
- `update_plot()`
- `rebuild_plots()`

---

## Entry points

### 1. **GUI App** (`main.py`)
**Use:** Interactive data acquisition with real-time visualization

```bash
python3 main.py
```

**Workflow:**
1. Choose mode (Acquire data / Load from file)
2. For acquiring select channels and signal types / For playback load file to play
3. Click "Start"
4. Data displays in real-time
5. Click "Stop"

---

### 2. **Commandline acquisition** (`acquire.py`)
**Use:** Quick terminal-based acquisition without GUI

```bash
# Basic usage (reads MAC from .env if --mac omitted)
python3 acquire.py --mac <MAC_ADDRESS> -c A1

# Multiple channels
python3 acquire.py --mac <MAC_ADDRESS> -c A1,D1

```

###  Saved data files in `data/recordings/`

**Filename Format:**
```
data_recording_YYYY-MM-DD_HH-MM_<signal_type>.txt
```

---

## Dependencies

- **Python 3.7+**
- **PyQt5** - GUI framework
- **FastAPI/Uvicorn** - REST API backend
- **Matplotlib** - Real-time plotting
- **PyBluez** - Bluetooth connectivity
- **numpy** - Data processing
- **pyserial** - Serial communication
- **pandas** - Dataframe parsing and saving
- **requests** - API client with retries
- **python-dotenv** - Load `.env` configuration

---

## BITalino Hardware Pin Mapping

**Physical pins on your BITalino board map to software channels as follows:**

| Physical Pin | Software Channel | Type | Use |
|--------------|------------------|------|-----|
| A1 - A6 | `A1` - `A6` | Analog input | Sensors (ECG, EMG, ACC, EDA, etc.) |
| I1 | `D0` | Digital input | Button, switch, or digital sensor |
| 02/I2 | `D1` | Digital input | Button, switch, or digital sensor |
| 01 | `D2` | Digital input | Button, switch, or digital sensor |
| PWM | - | Digital output | Control LEDs, motors (not acquired) |

**Example:**
- To read button on pin **I1** → select channel `D0` in GUI
- To read button on pin **02/I2** → select channel `D1` in GUI
- To read accelerometer on pins **A1-A3** → select channels `A1,A2,A3` with signal type "acc"

---

## Troubleshooting

### Bluetooth connection issues

**Important:** BITalino devices don't need to be "connected" via bluetoothctl. 
They only need to be **paired** and **trusted**. The application connects directly via RFCOMM.

**Initial pairing (one-time setup):**
```bash
bluetoothctl
# > scan on
# > pair <MAC_ADDRESS>
# > trust <MAC_ADDRESS>
# > exit
```

**After pairing, just run the GUI:**
```bash
./start_gui.sh
```

**Optional: Bind rfcomm device (for serial access):**
```bash
sudo rfcomm release /dev/rfcomm0
sudo rfcomm bind /dev/rfcomm0 <MAC_ADDRESS> 1
```

---

### Device permissions

If you get permission errors accessing `/dev/rfcomm0`:
```bash
# Add your user to dialout group
sudo usermod -a -G dialout $USER
# Log out and log back in for changes to take effect
```

