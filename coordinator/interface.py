#!/usr/bin/env python3
"""
Qt-based GUI interface for QR Code Scanner
Provides a responsive window with camera selector and live camera feed display.
"""

import sys

import cv2
from PyQt5.QtWidgets import QApplication

from components.camera_interface import CameraInterface


def main():
    """Main entry point."""
    # Check dependencies
    try:
        import cv2
        from PyQt5.QtWidgets import QApplication

        print(f"OpenCV version: {cv2.__version__}")
    except ImportError as e:
        print(f"Error: Missing dependency - {e}")
        print("Please install required packages: pip install opencv-python PyQt5")
        sys.exit(1)

    app = QApplication(sys.argv)
    # Use system default style for better Linux compatibility

    # Create and show the main window
    window = CameraInterface()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
