import numpy as np
import bluetooth # pip3 install git+https://github.com/pybluez/pybluez.git
import serial # pyserial
from serial.tools import list_ports
import time
import math
import logging
import os

class BITalino:
    def __init__(self, macAddress=None, timeout=10):
        self.socket = None
        self.analogChannels = []
        self.number_bytes = None
        self.macAddress = macAddress
        self.serial = False

        if os.path.exists('/dev/rfcomm0'): # try rfcomm0 first
            logging.info("Using rfcomm0 serial port")
            import serial
            self.socket = serial.Serial('/dev/rfcomm0', 115200, timeout=timeout)
            self.serial = True
            return
        # fallback, direct Bluetooth RFCOMM
        elif macAddress and ":" in macAddress and len(macAddress) == 17: 
            logging.info(f"Using direct Bluetooth: {macAddress}:1")
            import bluetooth
            self.socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            self.socket.settimeout(timeout)
            self.socket.connect((macAddress, 1))
            self.serial = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            if self.socket is not None:
                try:
                    self.stop()
                except Exception:
                    pass
                try:
                    self.socket.close()
                except Exception:
                    pass
        finally:
            self.socket = None

    def find(self, serial=False):
        try:
            if serial: # filter ports containing 'bitalino' or look like serial ports
                nearby_devices = [port[0] for port in list_ports.comports() if ('bitalino' in port[0].lower() or 'com' in port[0].lower())]
            else: # return list of (address, name) for discovered bluetooth devices
                nearby_devices = bluetooth.discover_devices(lookup_names=True)
            return nearby_devices
        except Exception as e:
            logging.exception("Error finding devices")
            return []    
        
    def open(self, macAddress=None, SamplingRate=1000, timeout: float = 5.0):
        """Open connection to BITalino device over Bluetooth or serial.
        """
        if not macAddress:
            raise TypeError("MAC address or serial port is needed to connect")

        self.macAddress = macAddress
        try:
            if ":" in macAddress and len(macAddress) == 17:
                self.socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
                self.socket.settimeout(timeout)
                self.socket.connect((macAddress, 1))
                self.serial = False
            else: # treat as serial port path
                self.socket = serial.Serial(macAddress, 115200, timeout=timeout)
                self.serial = True

            # sampling rate
            variableToSend = {1000: 0x03, 100: 0x02, 10: 0x01, 1: 0x00}.get(SamplingRate, None)
            if variableToSend is None:
                raise ValueError(f"Invalid sampling rate {SamplingRate}")

            variableToSend = int((variableToSend << 6) | 0x03)
            self.write(variableToSend)
            return True
        except Exception:
            logging.exception("Error opening connection to %s", macAddress)
            # ensure partial resources are closed
            try:
                if self.socket is not None:
                    self.socket.close()
            except Exception:
                pass
            self.socket = None
            raise

    def start(self, analogChannels=None):
        if analogChannels is None:
            analogChannels = [0, 1, 2, 3, 4, 5]
        self.analogChannels = list(dict.fromkeys(analogChannels))  # preserve order, remove duplicates
        if len(self.analogChannels) == 0 or len(self.analogChannels) > 6:
            raise ValueError("Invalid analog channels")

        bit = 1
        for i in self.analogChannels:
            bit |= 1 << (2 + i)
        self.write(bit, retries=3, backoff=0.15)
        return True

    def stop(self):
        try:
            self.write(0)
            return True
        except Exception:
            logging.exception("Error stopping device")
            return False

    def close(self):
        try:
            if self.socket is not None:
                try:
                    self.socket.close()
                except Exception:
                    pass
            self.socket = None
            return True
        except Exception:
            logging.exception("Error closing device")
            return False

    def battery(self, threshold=0):
        """
        Check battery level and optionally set low-battery threshold.
        
        Args:
            threshold: Battery voltage threshold (0-63). 
                      0 = just read current level (default)
                      1-63 = set threshold (device will indicate when below this)
                      
        Returns:
            int: Current battery level (0-100%)
            
        Example:
            level = device.battery()  # Read current level
            level = device.battery(threshold=30)  # Set threshold at ~3.4V
        """
        if threshold < 0 or threshold > 63:
            raise ValueError("Battery threshold must be 0-63")
        
        # Command byte: bits 7-6 = 00, bits 5-0 = threshold value
        cmd = threshold & 0x3F
        self.write(cmd)
        
        # Read response (1 byte with battery level)
        try:
            if self.serial:
                response = self.socket.read(1)
            else:
                response = self.socket.recv(1)
            
            if response:
                # Battery level is in bits 0-6 (0-100%)
                level = response[0] & 0x7F
                logging.info(f"Battery level: {level}%")
                return level
            else:
                logging.warning("No battery response from device")
                return None
        except Exception as e:
            logging.exception("Error reading battery level")
            return None

    def write(self, data=0, retries: int = 1, backoff: float = 0.1):
        """Write single control byte to device. (Helps recover from occasional BT or serial hiccups without requiring full reconnect.)
        """
        if self.socket is None:
            error_msg = (
                "No connection established to BITalino device. "
                "Device may not have been opened with open(), or connection was closed. "
                f"MAC Address: {self.macAddress}, Serial: {self.serial}"
            )
            raise TypeError(error_msg)
        attempt = 0
        last_exc = None
        while attempt <= retries:
            try:
                if self.serial:
                    self.socket.write(bytes([data]))
                else:
                    self.socket.send(bytes([data]))
                if attempt > 0:
                    logging.info("BITalino.write succeeded on retry #%d (data=%s)", attempt, data)
                return True
            except Exception as e:
                last_exc = e
                # Detailed logging to capture errno/repr and short hex of data
                try:
                    errno = getattr(e, 'errno', None)
                except Exception:
                    errno = None
                logging.warning("BITalino.write failed (attempt=%d, data=%s, serial=%s, err=%s, errno=%s)", attempt, data, self.serial, repr(e), errno)
                if attempt < retries:
                    import time
                    time.sleep(backoff) # small backoff before retry
                    attempt += 1
                    continue
                # no retries left, log exception and re-raise
                logging.exception("BITalino.write: final failure after %d attempts", attempt)
                raise
        raise last_exc or RuntimeError("Unknown error in write") # if exit loop without returning/raising

    def read(self, nSamples=100, timeout: float = 5.0):
        if self.socket is None:
            raise TypeError("Input connection is needed.")
        # Check if analogChannels is initialized and set to valid list
        if not self.analogChannels:
            raise ValueError("Analog channels must be specified before reading.")

        nChannels = len(self.analogChannels)
        if nChannels <= 4:
            self.number_bytes = int(math.ceil((12 + 10 * nChannels) / 8))
        else:
            self.number_bytes = int(math.ceil((52 + 6 * (nChannels - 4)) / 8))

        dataAcquired = np.zeros((5 + nChannels, nSamples))  # prepare matrix to hold data

        if self.serial: # reading method chosen based on connection type
            logging.debug("Reading from serial...")
            reader = lambda n: self.socket.read(n)
        else:
            logging.debug("Reading from Bluetooth...")
            reader = lambda n: self.socket.recv(n)

        Data = b''
        sampleIndex = 0
        start_time = time.time()
        while sampleIndex < nSamples:
            # read until have at least one packet
            try:
                while len(Data) < self.number_bytes:
                    chunk = reader(self.number_bytes - len(Data))
                    if not chunk:
                        # timeout or no data available
                        if time.time() - start_time > timeout:
                            raise TimeoutError("Timed out waiting for data")
                        continue
                    Data += chunk
            except Exception:
                logging.exception("Error while reading from device")
                raise

            decoded = self.decode(Data)  # decode the collected data
            if isinstance(decoded, np.ndarray) and decoded.size != 0:
                dataAcquired[:, sampleIndex] = decoded.T
                Data = b''
                sampleIndex += 1
            else:
                # if decode failed, shift buffer by one and retry to avoid deadlock
                Data = Data[1:]
                logging.debug("Decode failed, shifting buffer and retrying")

        return dataAcquired

    def decode(self, data, nAnalog=None):
        if nAnalog == None: nAnalog = len(self.analogChannels)
        if nAnalog <= 4:
            number_bytes = int(math.ceil((12. + 10. * nAnalog) / 8.))
        else:
            number_bytes = int(math.ceil((52. + 6. * (nAnalog - 4)) / 8.))
        
        nSamples = len(data) // number_bytes
        res = np.zeros(((nAnalog + 5), nSamples))
        
        j, x0, x1, x2, x3, out, inp, col, line = 0, 0, 0, 0, 0, 0, 0, 0, 0
        encode01 = 0x01
        encode03 = 0x03
        encodeFC = 0xFC
        encodeFF = 0xFF
        encodeC0 = 0xC0
        encode3F = 0x3F
        encodeF0 = 0xF0
        encode0F = 0x0F
        
        CRC = data[j + number_bytes - 1] & encode0F
        for byte in range(number_bytes):
            for bit in range(7, -1, -1):
                inp = data[byte] >> bit & encode01
                if byte == (number_bytes - 1) and bit < 4:
                    inp = 0
                out = x3
                x3 = x2
                x2 = x1
                x1 = out^x0
                x0 = inp^out
 
        if CRC == ((x3<<3)|(x2<<2)|(x1<<1)|x0):
            try:
                def store(value): # function to write to result and increment line
                    nonlocal line
                    res[line, col] = value
                    line += 1

                store((data[j + number_bytes - 1] >> 4) & 0x0F) # Sequence number

                # Digital channels D0 to D3 from a single byte
                # TODO: there are only three digital channels on BITalino? confirm mapping
                digital_byte = data[j + number_bytes - 2]
                for bit in range(7, 3, -1):  # bits 7 to 4
                    store((digital_byte >> bit) & 0x01)

                # Analog channel decoding
                analog_rules = [
                    [(-2, 0x0F, 6), (-3, 0xFC, -2)],    # A0
                    [(-3, 0x03, 8), (-4, 0xFF,  0)],    # A1
                    [(-5, 0xFF, 2), (-6, 0xC0, -6)],    # A2
                    [(-6, 0x3F, 4), (-7, 0xF0, -4)],    # A3
                    [(-7, 0x0F, 2), (-8, 0xC0, -6)],    # A4
                    [(-8, 0x3F, 0)]                     # A5
                ]

                #max_channels = 6 if res.shape[0] == 11 else 5
                max_channels = res.shape[0] - 5
                for i in range(max_channels):
                    value = 0
                    for byte_offset, mask, shift in analog_rules[i]:
                        part = data[j + number_bytes + byte_offset] & mask
                        if shift >= 0:
                            value |= part << shift
                        else:
                            value |= part >> -shift
                    store(value)

            except Exception as e:
                print(f"Exception decoding frame: {e}")
            return res
        # CRC check failed
        else:
            return []


