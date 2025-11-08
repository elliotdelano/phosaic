#!/usr/bin/env python3
"""
VideoThread for capturing and processing video frames.
"""

from PyQt5.QtCore import QThread, pyqtSignal

from vision import QRCodeScanner


class VideoThread(QThread):
    """Thread for capturing and processing video frames."""

    frame_ready = pyqtSignal(object, list)  # frame, qr_codes

    def __init__(self, camera_index=0):
        super().__init__()
        self.camera_index = camera_index
        self.cap = None
        self.running = False
        self.qr_scanner = QRCodeScanner()
        self.qr_scanner.camera_index = camera_index

    def run(self):
        """Main thread loop for video capture."""
        # Initialize camera through QR scanner
        if not self.qr_scanner.initialize_camera():
            return

        self.running = True

        while self.running:
            ret, frame = self.qr_scanner.cap.read()
            if ret:
                # Detect QR codes using scanner
                qr_codes = self.qr_scanner.detect_qr_codes(frame)
                self.frame_ready.emit(frame, qr_codes)
            else:
                break

        if self.qr_scanner.cap:
            self.qr_scanner.cap.release()

    def stop(self):
        """Stop the video thread."""
        self.running = False
        self.wait()
