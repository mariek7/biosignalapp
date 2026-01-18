import numpy as np

class SignalType:
    def __init__(self, name, unit, ylim, sampling_rate, transfer_function=None):
        self.name = name
        self.unit = unit
        self.ylim = ylim
        self.sampling_rate = sampling_rate
        self.transfer_function = transfer_function or (lambda x: x)

    def apply_transfer(self, adc_data):
        return self.transfer_function(adc_data)

# transfer functions
def ecg_transfer(adc_data, adc_bits=8, vcc=3.0, gain=1900):
    adc_data = np.asarray(adc_data, dtype=np.float32)
    adc_max = 2**adc_bits - 1
    ecg_v = ((adc_data / adc_max) - 0.5) * vcc / gain
    return ecg_v * 1000  # mV

def eeg_transfer(adc_data, n=10, vcc=3.3, g_eeg=41782):
    adc_data = np.asarray(adc_data).flatten().astype(np.float32)
    eeg_v = ((adc_data / (2**n-1)) - 0.5) * vcc / g_eeg
    return eeg_v * 1e6  # μV

def emg_transfer(adc_data, n=6, vcc=3.3, g_emg=1009):
    adc_data = np.asarray(adc_data, dtype=np.float32)
    emg_v = ((adc_data / (2**n-1)) - 0.5) * vcc / g_emg
    return emg_v * 1000  # mV

def acc_transfer(adc_data, c_min=2, c_max=4, scale=6.0):
    adc_data = np.asarray(adc_data, dtype=np.float32)
    return ((adc_data - c_min) / (c_max - c_min)) * scale - (scale / 2)

def eda_transfer(adc_data, adc_bits=10, vcc=3.3, r_div=560000): # TODO: check from BITalino docs
    adc_data = np.asarray(adc_data, dtype=np.float32)
    adc_max = 2**adc_bits - 1
    v_eda = (adc_data / adc_max) * vcc
    eda_uS = v_eda / (r_div * (vcc - v_eda)) * 1e6  # μS
    return eda_uS

signal_types = {
    'ecg': SignalType('ecg', 'mV', (-200, 200), 1000, transfer_function=ecg_transfer),
    'eeg': SignalType('eeg', 'μV', (-40, 40), 100, transfer_function=eeg_transfer),
    'emg': SignalType('emg', 'mV', (-20, 20), 1000, transfer_function=emg_transfer),
    'acc': SignalType('acc', 'g', (-3, 3), 100, transfer_function=acc_transfer),
    'eda': SignalType('eda', 'μS', (0, 100), 4, transfer_function=eda_transfer),
    'None': SignalType('raw', None, (-45, 45), 100, None)
}
