#!/usr/bin/env python3
"""
CameraInterface widget component for the QR Code Scanner application.
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .video_widget import VideoWidget


class CameraInterface(QGroupBox):
    """A widget group for the camera feed and its controls."""

    toggle_camera_clicked = pyqtSignal()
    camera_selection_changed = pyqtSignal(int)
    qr_detected = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__("Camera Feed", parent)
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface for this widget."""
        layout = QVBoxLayout(self)
        controls_layout = QHBoxLayout()

        self.start_stop_btn = QPushButton("Start Camera")
        self.start_stop_btn.clicked.connect(self.toggle_camera_clicked.emit)
        controls_layout.addWidget(self.start_stop_btn)

        controls_layout.addWidget(QLabel("Camera:"))
        self.camera_combo = QComboBox()
        self.camera_combo.currentIndexChanged.connect(
            self.camera_selection_changed.emit
        )
        controls_layout.addWidget(self.camera_combo)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        self.video_widget = VideoWidget()
        layout.addWidget(self.video_widget)

    def on_cameras_enumerated(self, cameras):
        """Slot to populate the camera dropdown list."""
        self.camera_combo.clear()
        self.camera_combo.addItems(cameras)
        if cameras and "No cameras found" in cameras[0]:
            self.start_stop_btn.setEnabled(False)
        else:
            self.start_stop_btn.setEnabled(True)

    def on_frame_ready(self, frame, qr_codes):
        """Slot to handle a new frame from the camera manager."""
        self.video_widget.set_frame(frame, qr_codes)
        if qr_codes:
            self.qr_detected.emit(qr_codes)

    def set_running_state(self, is_running):
        """Update the UI to reflect the camera's running state."""
        self.start_stop_btn.setText("Stop Camera" if is_running else "Start Camera")
        self.camera_combo.setEnabled(not is_running)
        if not is_running:
            self.video_widget.clear()
