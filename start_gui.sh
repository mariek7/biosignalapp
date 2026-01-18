#!/bin/bash
# Start FastAPI server and launch PyQt5 GUI

set -e
cd "$(dirname "$0")"

API_PORT="8000" # TODO: make configurable

[ -f .env ] && export $(grep -E '^(MAC_ADDRESS|DEVICE_MAC)=' .env | xargs) # load .env

echo "Starting BITalino GUI..."
[ ! -z "$MAC_ADDRESS" ] && echo "Device: $MAC_ADDRESS"

# If using direct MAC (Bluetooth), proactively disconnect stale session
if [[ "$MAC_ADDRESS" == *:* ]]; then
    echo "Ensuring Bluetooth device is free..."
    bluetoothctl disconnect "$MAC_ADDRESS" >/dev/null 2>&1 || true
fi

# ensure rfcomm binding is fresh when using /dev/rfcomm0
if [ "$MAC_ADDRESS" = "/dev/rfcomm0" ]; then
    if [ -z "$DEVICE_MAC" ]; then
        echo "DEVICE_MAC not set in .env; skipping rfcomm bind"
    else
        echo "Rebinding /dev/rfcomm0 to $DEVICE_MAC (channel 1)..."
        # Disconnect Bluetooth first to free the channel
        bluetoothctl disconnect "$DEVICE_MAC" >/dev/null 2>&1 || true
        sleep 1
        # Release rfcomm bindings
        sudo rfcomm release all >/dev/null 2>&1 || true
        sudo rfcomm release /dev/rfcomm0 >/dev/null 2>&1 || true
        sleep 1
        # Bind and set permissions
        sudo rfcomm bind /dev/rfcomm0 "$DEVICE_MAC" 1 || {
            echo "Warning: Could not bind rfcomm0 (device may be busy)"
            echo "Try: sudo systemctl restart bluetooth"
            exit 1
        }
        sudo chmod a+rw /dev/rfcomm0 || true
    fi
fi

cleanup() {
    [ ! -z "$API_PID" ] && kill "$API_PID" 2>/dev/null || true # cleanup on exit
}
trap cleanup EXIT INT TERM

# kill existing API server
lsof -Pi :$API_PORT -sTCP:LISTEN -t 2>/dev/null | xargs kill 2>/dev/null || true
sleep 1

# start API
echo "Starting API server..."
python3 -m uvicorn api.server:app --host 127.0.0.1 --port $API_PORT > api_server.log 2>&1 &
API_PID=$!
for i in {1..30}; do
    curl -s http://127.0.0.1:$API_PORT/docs > /dev/null 2>&1 && break
    kill -0 "$API_PID" 2>/dev/null || { echo "API server failed. See api_server.log"; exit 1; }
    sleep 1
done

echo "Launching GUI..."
python3 main.py
