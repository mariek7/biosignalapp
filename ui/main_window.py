import os
# Force pyqtgraph and matplotlib to use PyQt5 (avoid mixing PyQt6/PyQt5)
os.environ.setdefault('PYQTGRAPH_QT_LIB', 'PyQt5')
os.environ.setdefault('MPLBACKEND', 'Qt5Agg')
from core.signal_type import signal_types, eeg_transfer, ecg_transfer, emg_transfer, acc_transfer

from dotenv import load_dotenv
import sys
import os
import json
import requests
import numpy as np
import pandas as pd
import pyqtgraph as pg
from datetime import datetime
from PyQt5 import QtWidgets, QtCore, QtGui
from datetime import time
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BITalino biosignals data acquisition for linux")
        # ensure window opens within visible area 
        #try:
        #    self.move(100, 100)
        #except Exception:
        #    pass
        self.current_filename = ''
        #self.channel_to_plot = 'A1' 

        self.playback_mode = False
        self.playback_timer = QtCore.QTimer()
        self.playback_timer.timeout.connect(self.update_playback)
        self.playback_times = []
        self.playback_data = {}
        self.playback_index = 0

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot)

        # Main plot canvas (smaller height to stack multiple small plots)
        self.plot_widget = FigureCanvas(Figure(figsize=(14, 8)))
        self.plot_widget.setMinimumHeight(500)
        self.plot_widget_isVisible = True
        self.plot_fig = self.plot_widget.figure
        # create a default axis so older methods (init_data) can run before any selection
        self.ax = self.plot_fig.add_subplot(111)
        self.plot_axes = []        # list of matplotlib axes (one per subplot or a single combined axis)
        self.lines = []            # list of Line2D objects (one per channel)
        
        self.per_channel_controls_panel = QtWidgets.QWidget()  # Changed from QScrollArea
        per_channel_main_layout = QtWidgets.QVBoxLayout()
        per_channel_main_layout.setContentsMargins(0, 0, 0, 0)

###
        self.hide_all_plots_button = QtWidgets.QPushButton("Hide All")
        self.hide_all_plots_button.clicked.connect(self.toggle_all_plots_visibility)
        self.hide_all_plots_button.setEnabled(False)
        self.hide_all_plots_button.setToolTip("Select channels first")
        self.per_channel_ui = {} 

        self.per_channel_controls_panel = QtWidgets.QWidget()
        per_channel_main_layout = QtWidgets.QVBoxLayout()
        per_channel_main_layout.setContentsMargins(0, 0, 0, 0)

        # Fixed header
        header_widget = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setContentsMargins(5, 5, 5, 5)
        header_layout.addStretch()
        header_layout.addWidget(self.hide_all_plots_button)
        header_layout.addStretch()
        header_widget.setLayout(header_layout)
        per_channel_main_layout.addWidget(header_widget)
        per_channel_main_layout.addSpacing(15)

        self.per_channel_controls_layout = QtWidgets.QVBoxLayout()
        per_channel_main_layout.addLayout(self.per_channel_controls_layout)
        per_channel_main_layout.addStretch()
        self.per_channel_controls_panel.setLayout(per_channel_main_layout)

        self.controls_scroll = QtWidgets.QScrollArea()
        self.controls_scroll.setWidgetResizable(True)
        self.controls_scroll.setMinimumWidth(220)
        self.controls_scroll.setWidget(self.per_channel_controls_panel)

###
  
        self.init_data()
        # print signal type and sampling rate
        self.signal = signal_types.get(os.getenv('signal_type', 'eeg'), signal_types['eeg'])
        self.sampling_rate = self.signal.sampling_rate

        # channel choose (checkbox + type dropdown per channel)
        layout_channel_selection = QtWidgets.QHBoxLayout()
        layout_channel_selection.addWidget(QtWidgets.QLabel("Channels:"))
        self.channel_controls = []  # list of tuples (name, checkbox, combobox)
        sensor_items = ["Not selected", "eeg", "ecg", "acc", "emg", "eda", "btn", "raw"]
        # TODO: ^-- was this for dropdown under channel checkboxes, then unnecessary?
        for i in range(1, 7):
            name = f"A{i}"
            cb = QtWidgets.QCheckBox(name)
            cb.toggled.connect(lambda checked: self.selection_changed())
            # vertical container for checkbox only (no dropdown here)
            container = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout()
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(cb)
            container.setLayout(v)
            layout_channel_selection.addWidget(container)
            # store (name, checkbox) only
            self.channel_controls.append((name, cb))     

        # digital channels: add to same top row as analog channels
        self.digital_channel_controls = []
        sensor_items_d = ["Not selected", "btn", "raw"]
        # Map digital channels to physical pin labels
        # TODO: Check whats the third channel, 01
        digital_pin_labels = {
            "D0": "D0 (I1)",
            "D1": "D1 (I2/02)",
            # "D2": "D2 (01)", 
        }
        for i in range(0, 2): # D0, D1
            name = f"D{i}"
            label = digital_pin_labels.get(name, name)
            cb = QtWidgets.QCheckBox(label)
            cb.toggled.connect(lambda checked: self.selection_changed())
            container = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout()
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(cb)
            container.setLayout(v)
            layout_channel_selection.addWidget(container)
            self.digital_channel_controls.append((name, cb))

        # plot options (mode + hide)
        layout_plot_style_controls = QtWidgets.QHBoxLayout()
        layout_plot_style_controls.addWidget(QtWidgets.QLabel("Plot mode:"))
        self.plot_mode_combo = QtWidgets.QComboBox()
        self.plot_mode_combo.addItems(["Separate","Combined"])
        self.plot_mode_combo.setCurrentIndex(0)
        self.plot_mode_combo.currentIndexChanged.connect(lambda _: self.selection_changed())
        layout_plot_style_controls.addWidget(self.plot_mode_combo)
        layout_plot_style_controls.addStretch()
        #layout_plot_style_controls.addWidget(self.hide_all_plots_button)

        # signal type choose
        layout_global_signal_type = QtWidgets.QHBoxLayout()
        self.signals_combo_box = QtWidgets.QComboBox()
        self.signals_combo_box.addItems(list(signal_types.keys()))
    

        #layout_global_signal_type.addWidget(QtWidgets.QLabel(f"Signal type: eeg (sampling rate: {self.sampling_rate}, unit: {self.signal.unit})"))

        layout_plot_visibility_controls = QtWidgets.QHBoxLayout()

        self.layout_plot_and_controls = QtWidgets.QHBoxLayout()
        self.layout_plot_and_controls.addWidget(self.plot_widget, 1)
        self.layout_plot_and_controls.addWidget(self.controls_scroll)

        # box for acquire or load file
        layout_mode_and_controls = QtWidgets.QHBoxLayout()

        # mode selector - acquire OR playback
        layout_operation_mode_selector = QtWidgets.QHBoxLayout()
        layout_operation_mode_selector.addWidget(QtWidgets.QLabel("Mode:"))
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["Acquire data", "Load from file"])
        self.mode_combo.currentTextChanged.connect(self.mode_changed)
        layout_operation_mode_selector.addWidget(self.mode_combo)
        layout_operation_mode_selector.addStretch()

        # Control buttons
        layout_action_buttons = QtWidgets.QHBoxLayout()

        # Load button (only for Playback mode)
        self.load_button = QtWidgets.QPushButton("Load File")
        self.load_button.clicked.connect(self.load_file)
        self.load_button.setEnabled(False)  # disabled until Playback mode
        self.load_button.setToolTip("Select Load from file -mode first")

        # Start/Play button (changes label by mode)
        self.start_pause_button = QtWidgets.QPushButton("▶ Start")
        self.start_pause_button.clicked.connect(self.toggle_play_pause)
        self.start_pause_button.setEnabled(True)

        # Stop button (both modes)
        self.stop_button = QtWidgets.QPushButton("⏹ Stop && Save")
        self.stop_button.clicked.connect(self.stop_plotting_and_save)
        self.stop_button.setEnabled(False)

        layout_action_buttons.addWidget(self.load_button)
        layout_action_buttons.addWidget(self.start_pause_button)
        #layout_action_buttons.addWidget(self.pause_button) 
        layout_action_buttons.addWidget(self.stop_button)

        # Combined layout
        layout_mode_and_controls.addLayout(layout_operation_mode_selector)
        layout_mode_and_controls.addLayout(layout_action_buttons)

        # info text box
        layout_status_log = QtWidgets.QHBoxLayout()
        self.info_text_box = QtWidgets.QTextEdit()
        self.info_text_box.setReadOnly(True)
        self.info_text_box.setFixedHeight(70)
        self.info_text_box.setText(f"")
        layout_status_log.addWidget(self.info_text_box)

        layout = QtWidgets.QVBoxLayout()
        #layout.addWidget(self.text_box)
        layout.addWidget(QtWidgets.QLabel(f"MAC address: {self.mac_address}"))
        #layout.addWidget(self.change_mac_button)
        layout.addLayout(layout_channel_selection)

        # line
        h_sep1 = QtWidgets.QFrame()
        h_sep1.setFrameShape(QtWidgets.QFrame.HLine)
        layout.addWidget(h_sep1)

        layout.addLayout(layout_mode_and_controls)    

        layout.addWidget(h_sep1) 

        layout.addLayout(self.layout_plot_and_controls)
        layout.addLayout(layout_plot_style_controls)

        layout.addLayout(layout_global_signal_type)

        layout.addLayout(layout_plot_visibility_controls)

  
        layout.addLayout(layout_status_log)
        
        layout.addStretch()
        layout.addWidget(QtWidgets.QLabel("-"))
        central_widget = QtWidgets.QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

    def load_file(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load BITalino file", "data/recordings/", "Text files (*.txt)")
        if not filename: 
            return

        # clear selections
        for name_cb_pair in self.channel_controls + self.digital_channel_controls:
            name, cb = name_cb_pair if len(name_cb_pair) == 2 else (name_cb_pair[0], name_cb_pair[1])
            cb.setChecked(False)
            
        # reset playback state for new file
        self.playback_mode = True
        self.playback_index = 0
        self.playback_timer.stop()
        self.timer.stop()
        self.start_pause_button.setText("▶ Play")
        
        self.current_filename = filename
        
        # Read entire file
        with open(filename, 'r') as f:
            content = f.read()
        
        lines = content.splitlines()
        
        # Skip OpenSignals version header if present
        if lines and "# OpenSignals Text File Format. Version 1" in lines[0]:
            print("Skipping OpenSignals version header")
            lines = lines[1:]
        
        # Initialize defaults
        header_end_idx = 0
        channels, sensors = ['A1', 'A2'], ['raw', 'raw']
        sampling_rate = 100
        device_info = {}
        column_order = []
        
        # Parse header
        for i, line in enumerate(lines):
            if line.strip() == '# EndOfHeader':
                header_end_idx = i
                break
            if line.startswith('# {'):
                try:
                    import json
                    full_header = json.loads(line[2:].strip())
                    if isinstance(full_header, dict) and len(full_header) > 0:
                        device_mac = list(full_header.keys())[0]
                        device_info = full_header[device_mac]
                        channels = device_info.get('label', ['A1'])
                        sensors = device_info.get('sensor', ['raw'])
                        sampling_rate = device_info.get('sampling_rate', 100)
                        self.playback_sampling_rate = sampling_rate
                        column_order = device_info.get('column', [])
                        print(f"File sampling rate: {sampling_rate} Hz")
                        print(f"Header: channels={channels}, sensors={sensors}")
                        print(f"Columns: {column_order}")
                        #break
                except Exception as e:
                    print(f"Header parse error: {e}")
        
        # Dynamic column mapping
        label_to_col = {label: idx for idx, label in enumerate(column_order) if label in channels}
        
        #print(f"header_end_idx = {header_end_idx}")
        #print(f"lines[header_end_idx] = '{lines[header_end_idx][:50]}...'")
        #print(f"First 3 data lines:")
        #for i in range(header_end_idx+1, min(header_end_idx+4, len(lines))):
        #    print(f"  lines[{i}] = '{lines[i][:50]}'")

        # Parse data lines
        times, data = [], {}
        for line in lines[header_end_idx+1:]:
            if line.strip():
                parts = line.strip().split()
                if len(parts) >= len(column_order):
                    times.append(float(parts[0]))  # Time col 0
                    for ch in channels:
                        col_idx = label_to_col.get(ch, 5)
                        if col_idx < len(parts):
                            data.setdefault(ch, []).append(float(parts[col_idx]))
        
        print(f"Parsed {len(times)} samples from {len(lines[header_end_idx+1:])} data lines")
        
        # Store playback data
        self.playback_times = times
        self.playback_data = data
        self.playback_channel_types = dict(zip(channels, sensors))
        
        # Setup buffers
        self.selected_channels = channels
        self.data_buffers = {ch: [] for ch in channels}
        self.all_data = {ch: [] for ch in channels}
        self.all_time = []

              
        # Auto-select checkboxes
        for name_cb_pair in self.channel_controls + self.digital_channel_controls:
            name, cb = name_cb_pair if len(name_cb_pair) == 2 else (name_cb_pair[0], name_cb_pair[1])
            cb.setEnabled(False) # lock to file channes
            if name in channels:
                cb.setChecked(True)
        
        # Single call after all setup
        self.selection_changed()
        self.info_text_box.append(f"Loaded {filename} ({len(times)} samples, {len(channels)} channels: {channels})")



    def toggle_play_pause(self):
        """Single button: Start/Play Pause/Resume for both modes"""
        
        if self.playback_mode:
            if not hasattr(self, 'playback_times') or not self.playback_times:
                QtWidgets.QMessageBox.warning(self, "No file loaded", 
                    "Please load a file first before playing.")
                return
        else:
            channels, _ = self.get_selected_channels()
            if not channels:
                QtWidgets.QMessageBox.warning(self, "No channels selected",
                    "Please select at least one channel before starting.")
                return
        
        current_text = self.start_pause_button.text()
        
        if "Pause playback" in current_text or "Pause" in current_text:
            # PAUSE - stop both timers
            self.playback_timer.stop()
            self.timer.stop()
            if self.playback_mode:
                self.start_pause_button.setText("▶ Play")
            else:
                self.start_pause_button.setText("▶ Resume")
            self.info_text_box.append("Paused")
            
        elif "Resume" in current_text or "Play" in current_text or "Start" in current_text:
            # START/RESUME
            if self.playback_mode:
                playback_interval = max(1, int(1000 / self.playback_sampling_rate))
                self.playback_timer.start(playback_interval)
                self.start_pause_button.setText("⏸ Pause playback")
                self.info_text_box.append(f"Playing at {self.playback_sampling_rate} Hz")
            else:
                self.start_plotting()
                self.start_pause_button.setText("⏸ Pause")
                self.info_text_box.append("Acquisition started")
        
        self.update_button_states()



    def update_button_states(self):
        """Enable/disable buttons based on current state"""
        is_running = self.timer.isActive() or self.playback_timer.isActive()
        self.stop_button.setEnabled(is_running)
        #self.pause_button.setEnabled(is_running)



    def update_playback(self):
        if self.playback_index >= len(self.playback_times):
            self.playback_timer.stop()
            self.start_pause_button.setText("▶ Play")
            self.playback_index = 0
            self.info_text_box.append("Playback finished - end of file reached.")
            return
        
        window = int(self.playback_sampling_rate * 2)  # show 2s window
        end_idx = min(self.playback_index + window, len(self.playback_times))
        
        # fill buffers with current window
        self.time_buffer = self.playback_times[self.playback_index:end_idx]
        for ch in self.selected_channels:
            if ch in self.playback_data:
                self.data_buffers[ch] = self.playback_data[ch][self.playback_index:end_idx]
        
        # update plot
        for idx, ch in enumerate(self.selected_channels):
            if idx < len(self.lines):
                y = self.data_buffers.get(ch, [])
                x = self.time_buffer[:len(y)] if y else []
                self.lines[idx].set_data(x, y)
        
        # auto-scale
        if self.plot_axes:
            for ax in self.plot_axes:
                ax.relim()
                ax.autoscale_view()
            self.plot_widget.draw()
        
        # advance by 1 sample only
        self.playback_index += 1


    # acquire or playback mode 
    def mode_changed(self): 
        mode = self.mode_combo.currentText()
        
        if "Load from file" in mode:
            self.playback_mode = True
            self.start_pause_button.setText("▶ Play") 
            self.load_button.setEnabled(True)
            self.stop_button.setText("⏹ Stop")
        else:
            self.playback_mode = False
            self.start_pause_button.setText("▶ Start")
            self.load_button.setEnabled(False)
            self.stop_button.setText("⏹ Stop & Save")
            # enable channel selection when switching back to acquire mode
            for name_cb_pair in self.channel_controls + self.digital_channel_controls:
                name, cb = name_cb_pair if len(name_cb_pair) == 2 else (name_cb_pair[0], name_cb_pair[1])
                cb.setEnabled(True)
        
        self.timer.stop()
        self.playback_timer.stop()
        
        self.update_button_states()
        self.rebuild_plots()

    def init_data(self):
        load_dotenv()
        self.date_and_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
        self.mac_address = os.getenv('MAC_ADDRESS')
        signal_type_key = os.getenv('signal_type', 'None')
        self.signal = signal_types.get(signal_type_key, signal_types['None'])
        self.transfer_func = self.signal.transfer_function
        self.sampling_rate = self.signal.sampling_rate

        self.dt = 1.0 / self.sampling_rate
        self.t = 0
        self.time_buffer = []
        self.data_buffer = []
        self.all_time = []
        self.all_data = []
        self.ax.set_ylim(self.signal.ylim)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel(self.signal.unit)

    def get_selected_channels(self):
        """Return (channels, channel_types)"""
        channels = []
        channel_types = {}
        mapping = {'acc': 'ACCBITREV', 'ecg': 'ECGBIT', 'eeg': 'EEGBIT', 'emg': 'EMGBIT', 'eda': 'EDABIT', 'btn': 'BTN', 'raw': 'RAW'}
        
        # Analog channels
        for item in getattr(self, 'channel_controls', []):
            if len(item) == 2:
                name, cb = item
            else:
                name, cb = item[0], item[1]
            if cb.isChecked():
                channels.append(name)
                # check if UI exists and is valid
                if name in self.per_channel_ui:
                    ui = self.per_channel_ui[name]
                    try:
                        combo = ui[0]
                        st = combo.currentText()
                        if st and st != "Not selected":
                            channel_types[name] = mapping.get(st, st)
                    except RuntimeError:
                        pass
        
        # Digital channels
        for item in getattr(self, 'digital_channel_controls', []):
            if len(item) == 2:
                name, cb = item
            else:
                name, cb = item[0], item[1]
            if cb.isChecked():
                channels.append(name)
                if name in self.per_channel_ui:
                    ui = self.per_channel_ui[name]
                    try:
                        combo = ui[0]
                        st = combo.currentText()
                        if st and st != "Not selected":
                            channel_types[name] = mapping.get(st, st)
                    except RuntimeError:
                        pass
        
        return channels, channel_types



    def selection_changed(self):
        """Called whenever channel selection or plot mode changes. Rebuilds per channel UI and plots."""
            
        channels, channel_types = self.get_selected_channels()
        self.selected_channels = channels
        # preserve explicit types where possible
        self.selected_channel_types = channel_types.copy()

        self.hide_all_plots_button.setEnabled(len(channels) > 0)
        self.hide_all_plots_button.setText("Hide All")

        layout = self.per_channel_controls_layout 
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()

        mapping = {'acc': 'ACCBITREV', 'ecg': 'ECGBIT', 'eeg': 'EEGBIT', 'emg': 'EMGBIT', 'eda': 'EDABIT', 'btn': 'BTN', 'raw': 'RAW'}
        inv_map = {v: k for k, v in mapping.items()}  # for display names
        options = ["eeg", "ecg", "acc", "emg", "eda", "btn", "raw"]
        
        for ch in channels:
            row = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            lbl = QtWidgets.QLabel(ch)
            combo = QtWidgets.QComboBox()
            combo.addItems(options)
            
            # check if playback mode has file types
            file_type = None
            if self.playback_mode and hasattr(self, 'playback_channel_types') and ch in self.playback_channel_types:
                file_type = self.playback_channel_types[ch]
                display_type = inv_map.get(file_type, file_type.lower() if isinstance(file_type, str) else 'raw')
                combo.setCurrentText(display_type)
                combo.setEnabled(False)  # channel type from file
                #print(f"{ch}: Locked to {display_type} from file")
            else:
                # original logic for live mode
                cur = self.selected_channel_types.get(ch)
                if cur:
                    combo.setCurrentText(inv_map.get(cur, cur.lower()))
                else: # defaults
                    combo.setCurrentText('btn' if ch.startswith('D') else 'raw')
                    self.selected_channel_types[ch] = mapping.get(combo.currentText(), combo.currentText())
                combo.setEnabled(True)
            
            # store type regardless of source
            self.selected_channel_types[ch] = file_type or mapping.get(combo.currentText(), combo.currentText())
            
            combo.currentTextChanged.connect(lambda txt, ch=ch, mapping=mapping: self.selected_channel_types.__setitem__(ch, mapping.get(txt, txt)))
            hide_btn = QtWidgets.QPushButton("Hide")
            hide_btn.setCheckable(True)
            hide_btn.toggled.connect(lambda checked, ch=ch: self.toggle_channel_plot(ch, checked))
            
            h.addWidget(lbl)
            h.addWidget(combo)
            h.addWidget(hide_btn)
            row.setLayout(h)
            layout.addWidget(row)
            self.per_channel_ui[ch] = (combo, hide_btn)
        
        layout.addStretch()
        self.rebuild_plots()




    def rebuild_plots(self):
        channels = getattr(self, 'selected_channels', []) or []
        mode = self.plot_mode_combo.currentText() if hasattr(self, 'plot_mode_combo') else 'Combined'

        #channels to show
        visible_channels = [ch for ch in channels if not self.is_channel_hidden(ch)]

        if not visible_channels:
            self.plot_fig.clf()
            self.plot_axes = []
            self.lines = []
            self.plot_widget.draw()
            return

        self.plot_fig.clf()
        self.plot_axes = []
        self.lines = []
        self.visible_channel_map = {ch: i for i, ch in enumerate(visible_channels)} 

        colors = ['C0', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'C9']
        if mode == 'Combined' or len(channels) <= 1:
            ax = self.plot_fig.add_subplot(111)
            for idx, ch in enumerate(channels):
                line, = ax.plot([], [], colors[idx % len(colors)], label=ch)
                self.lines.append(line)
            if channels:
                ax.legend()
            self.plot_axes = [ax]
        else:
            n = len(visible_channels)
            for idx, ch in enumerate(channels):
                ax = self.plot_fig.add_subplot(n, 1, idx + 1)
                line, = ax.plot([], [], colors[idx % len(colors)], label=ch)
                ax.set_ylabel(ch)
                self.lines.append(line)
                self.plot_axes.append(ax)
            for i, ax in enumerate(self.plot_axes):
                if i < len(self.plot_axes) - 1:  # hide timeline on all but bottom plot
                    ax.tick_params(labelbottom=False)
                    ax.xaxis.set_ticks_position('none') 
                ax.tick_params(labeltop=False)  # no top labels
            self.plot_fig.subplots_adjust(hspace=0)  # zero vertical space between plots
            self.plot_fig.tight_layout(h_pad=0)      # extra tight packing
        self.plot_widget.draw()

    def is_channel_hidden(self, ch):
        """Check if channel is hidden (hide button state)"""
        if ch in self.per_channel_ui:
            _, hide_btn = self.per_channel_ui[ch]
            return hide_btn.isChecked()
        return False  # default visible


    def toggle_channel_plot(self, ch, hidden):
        """Hide/show channel plot and rebuild to resize."""
        self.rebuild_plots()  # rebuilds with visible channels only
        self.plot_widget.draw()
        ''''
        mode = self.plot_mode_combo.currentText() if hasattr(self, 'plot_mode_combo') else 'Combined'
        if mode == 'Combined':
            if idx < len(self.lines):
                self.lines[idx].set_visible(not hidden)
        else:
            if idx < len(self.plot_axes):
                self.plot_axes[idx].set_visible(not hidden)
        self.plot_widget.draw()
        '''

    def toggle_all_plots_visibility(self):
        """Hide/show all plots with one button"""
        if not self.plot_axes and not self.lines:
            return
            
        # Toggle between visible-hidden
        all_visible = all(ax.get_visible() for ax in self.plot_axes) if self.plot_axes else True
        new_state = not all_visible
        
        # Update button text
        self.hide_all_plots_button.setText("Show all" if new_state else "Hide all")
        
        # Hide/show all
        for ax in self.plot_axes:
            ax.set_visible(new_state)
        for line in self.lines:
            line.set_visible(new_state)
        
        self.plot_widget.draw()

    def hide_show_plot_widget(self):
        self.plot_widget.setVisible(not self.plot_widget_isVisible)
        self.plot_widget_isVisible = not self.plot_widget_isVisible

    def start_plotting(self):
        channels, channel_types = self.get_selected_channels()
        if not channels:
            QtWidgets.QMessageBox.warning(self, "No channels selected",
                                          "Please select at least one channel and a sensor type before starting acquisition.")
            return
        # validate types: BTN only on digital channels; analog channels cannot be BTN
        for ch, t in channel_types.items():
            if ch.startswith('A') and t == 'BTN':
                QtWidgets.QMessageBox.warning(self, "Invalid selection",
                                              f"Channel {ch} is analog and cannot be assigned type BTN (button).")
                return
            if ch.startswith('D') and t not in ('BTN', 'RAW'):
                QtWidgets.QMessageBox.warning(self, "Invalid selection",
                                              f"Channel {ch} is digital and accepts only 'btn' or 'raw' sensor types.")
                return
        self.selected_channels = channels
        self.selected_channel_types = channel_types
        # initialize buffers for each selected channel
        self.data_buffers = {ch: [] for ch in channels}
        self.all_data = {ch: [] for ch in channels}
        self.all_time = []
        # initialize error tracking for API failures
        self.consecutive_api_failures = 0
        self.max_api_failures = 10
        # rebuild the per-channel UI and plots according to current selection/mode
        self.selection_changed()

        self.info_text_box.append(f"Starting acquisition with channels {channels} and types {channel_types}")
        self.timer.start(300)    

    def stop_plotting_and_save(self):
        self.timer.stop()
        self.playback_timer.stop()

        if self.playback_mode:
            self.info_text_box.append("Playback stopped.")
            return

        channels = getattr(self, 'selected_channels', [])
        channel_types = getattr(self, 'selected_channel_types', {})
        
        # determine filename suffix from channel types
        if channel_types:
            # Use the first channel's type for filename
            first_type = list(channel_types.values())[0] if channel_types else 'eeg'
            # remove 'BIT' suffix and lowercase (ECGBIT -> ecg)
            signal_suffix = first_type.replace('BIT', '').lower() if 'BIT' in first_type else first_type.lower()
        else:
            signal_suffix = self.signal.name
        
        filename = f'data/recordings/data_recording_{self.date_and_time}_{signal_suffix}'
        channel_types = getattr(self, 'selected_channel_types', {})

        # prepare data and times for write_to_file
        times = self.all_time
        # ensure all channel buffers have same length as times
        data = {ch: getattr(self, 'all_data', {}).get(ch, []) if isinstance(getattr(self, 'all_data', {}), dict) else [] for ch in channels}

        # If internal per-frame append used non-equal lengths, pad shorter lists with empty strings in write_to_file
        # write text file in the same format as core.file_io
        from core.file_io import write_to_file
        out_path = f"{filename}.txt"
        try:
            write_to_file(out_path, self.mac_address or '', self.sampling_rate, times, data, channels, device_name=self.mac_address, sensor_types=channel_types)
            self.info_text_box.append(f"Data saved to file {out_path} (channels: {channels}, types: {channel_types})")
        except Exception as e:
            self.info_text_box.append(f"Error saving file: {e}")

        # also save a CSV for quick inspection
        try:
            df = pd.DataFrame({"Time (s)": times})
            for ch in channels:
                df[ch] = data.get(ch, [])
            df.to_csv(f"{filename}.csv", index=False)
        except Exception:
            pass


    def update_plot(self):
        try:
            params = {'macAdd': self.mac_address, 'samplingRate': self.sampling_rate, 'recordingTime': 1}
            response = requests.get("http://localhost:8000/bitalino-get/", params=params, timeout=30)
            if not response.ok:
                error_detail = response.text[:500]
                status = response.status_code
                
                if not hasattr(self, 'consecutive_api_failures'):  # track consecutive failures
                    self.consecutive_api_failures = 0
                    self.max_api_failures = 10
                
                self.consecutive_api_failures += 1
                
                if status == 503: # Service unavailable - device I/O error or other transient failure, give moment and retry
                    if self.consecutive_api_failures > 3:
                        msg = f"Device error (attempt {self.consecutive_api_failures}/{self.max_api_failures}): {error_detail[:100]}"
                    else:
                        msg = f"Device temporarily unavailable (retrying...)"
                    print(f"[{self.consecutive_api_failures}] API returned non-OK status {status}: {error_detail}")
                    self.info_text_box.append(msg)
                    
                    if self.consecutive_api_failures >= self.max_api_failures:
                        self.timer.stop()
                        self.info_text_box.append(f"Stopped: Device unresponsive after {self.max_api_failures} attempts. Check device connection.")
                        self.start_pause_button.setText("▶ Start")
                    return
                    
                elif status == 504: # Gateway timeout - Bluetooth/device timeout
                    self.consecutive_api_failures += 1
                    msg = f"Device timeout (attempt {self.consecutive_api_failures}/{self.max_api_failures})"
                    print(f"API returned timeout 504: {error_detail}")
                    self.info_text_box.append(msg)
                    
                    if self.consecutive_api_failures >= self.max_api_failures:
                        self.timer.stop()
                        self.info_text_box.append(f"Stopped: Device timeouts after {self.max_api_failures} attempts. Device may be out of range.")
                        self.start_pause_button.setText("▶ Start")
                    return
                    
                else:  # other errors
                    self.consecutive_api_failures += 1
                    print(f"API returned non-OK status {status}: {error_detail}")
                    self.info_text_box.append(f"API error {status}: {error_detail[:80]}")
                    
                    if self.consecutive_api_failures >= self.max_api_failures:
                        self.timer.stop()
                        self.info_text_box.append(f"Stopped after {self.max_api_failures} consecutive API errors")
                        self.start_pause_button.setText("▶ Start")
                    return

            self.consecutive_api_failures = 0  # reset failure counter after success

            from core.file_io import parse_acquisition_response
            try:
                all_df = parse_acquisition_response(response.text)
                #print(f"DEBUG-1: all_df.shape={all_df.shape if hasattr(all_df, 'shape') else 'NO SHAPE'}, columns={list(all_df.columns) if hasattr(all_df, 'columns') else 'NO COLUMNS'}")
            except Exception as e:
                print("Error parsing device response:", e)
                print("Response body:", response.text[:1000])
                return

            channel_types = getattr(all_df, 'attrs', {}).get('channel_types', {})

            #channels = getattr(self, 'selected_channels', [self.channel_to_plot])
            channels = getattr(self, 'selected_channels', [])

            if not channels:
                return

            # mapping sensor string -> transfer function
            SENSOR_TRANSFER = {
                'RAW': lambda x: x,
                'BTN': lambda x: x,
                'EDABIT': lambda x: x,
                'ECGBIT': ecg_transfer,
                'EEGBIT': eeg_transfer,
                'EMGBIT': emg_transfer,
                'ACCBIT': acc_transfer,
                'ACCBITREV': acc_transfer,
            }

            n_samples = None
            for ch in channels:
                if ch not in all_df.columns:
                    continue
                series = all_df[ch].values
                sensor = channel_types.get(ch)
                if sensor:
                    tf = SENSOR_TRANSFER.get(sensor.upper(), self.signal.transfer_function)
                else:
                    tf = self.signal.transfer_function
                transferred = tf(series)
                vals = transferred.tolist() if hasattr(transferred, 'tolist') else [float(x) for x in transferred]

                #print(f"DEBUG-2: ch={ch}, got {len(vals)} samples, sensor={sensor}")

                # append to buffers
                self.data_buffers.setdefault(ch, []).extend(vals)
                self.all_data.setdefault(ch, []).extend(vals)
                if n_samples is None:
                    n_samples = len(vals)
                    times = np.arange(self.t, self.t + n_samples * self.dt, self.dt)
                    self.t += n_samples * self.dt
                    #print(f"DEBUG-3: n_samples={n_samples}, times len={len(times)}")

            if n_samples is None:
                #print("DEBUG-4: n_samples is None - no data processed!")
                return

            self.all_time.extend(times)

            # update rolling buffers for plotting window (2s)
            window = int(self.sampling_rate * 2)
            for ch in channels:
                buf = self.data_buffers.get(ch, [])
                if len(buf) > window:
                    self.data_buffers[ch] = buf[-window:]
            # update time buffer
            self.time_buffer.extend(times)
            if len(self.time_buffer) > window:
                self.time_buffer = self.time_buffer[-window:]

            # ensure plot lines exist, rebuild if necessary
            if len(self.lines) < len(channels):
                self.rebuild_plots()

            # update lines (combined or separate modes)
            visible_channels = [ch for ch in channels if not self.is_channel_hidden(ch)]
            mode = self.plot_mode_combo.currentText() if hasattr(self, 'plot_mode_combo') else 'Combined'

            for idx, ch in enumerate(visible_channels):
                y = self.data_buffers.get(ch, [])
                x = self.time_buffer[-len(y):] if y else []
                if mode == 'Combined' or len(self.plot_axes) <= 1:
                    if idx < len(self.lines):
                        self.lines[idx].set_data(x, y)
                else:
                    if idx < len(self.lines):
                        self.lines[idx].set_data(x, y)
                        if idx < len(self.plot_axes):
                            ax = self.plot_axes[idx]
                            ax.relim()
                            ax.autoscale_view()

            # autoscale view for combined mode as well
            if self.plot_axes:
                for ax in self.plot_axes:
                    ax.relim()
                    ax.autoscale_view()

            self.plot_widget.draw()

        except Exception as e:
            print("Error:", e)
            # on error, try to keep buffers limited and continue
            try:
                if len(self.time_buffer) > self.sampling_rate * 2:
                    self.time_buffer = self.time_buffer[-self.sampling_rate * 2:]
            except Exception:
                pass
            try:
                self.plot_widget.draw()
            except Exception:
                pass

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()

    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
