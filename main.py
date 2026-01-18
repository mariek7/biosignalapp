#!/usr/bin/env python3
"""
Main entry point for biosignals GUI app.

Launches PyQt5 GUI for data acquisition and playback.

Usage:
    python3 main.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))) # ensure the project root is in the path
from ui.main_window import MainWindow # import main window class 
from PyQt5.QtWidgets import QApplication


def main():
    """Launch biosignals GUI app."""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
