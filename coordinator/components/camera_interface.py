#!/usr/bin/env python3
"""
CameraInterface main window component for QR Code Scanner application.
"""

import json

import cv2
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .video_widget import VideoWidget
from .video_thread import VideoThread
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from coordinator import Coordinator


class CameraInterface(QMainWindow):
    """Main window for camera interface with selector and feed display."""

    def __init__(self):
        super().__init__()
        self.video_thread = None
        self.current_camera = 0
        self.available_cameras = []
        self.coordinator = Coordinator()
        self.connected_ids = set()  # Track IDs we've already connected to

        self.init_ui()
        self.enumerate_cameras()

        # Set up timer for UI updates (check every 100ms)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(100)

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Camera Interface")
        self.setGeometry(100, 100, 1000, 700)
        self.setMinimumSize(600, 400)

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Top control panel
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)

        # Video display area
        self.video_widget = VideoWidget()
        main_layout.addWidget(self.video_widget, 1)  # Give it stretch factor of 1

        # Status display area
        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(150)
        self.status_text.setReadOnly(True)
        self.status_text.append("Ready to scan QR codes for peer connections...")
        main_layout.addWidget(self.status_text)

    def create_control_panel(self):
        """Create the top control panel."""
        panel = QWidget()
        panel.setMaximumHeight(60)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)

        # Camera selector label
        camera_label = QLabel("Camera:")
        layout.addWidget(camera_label)

        # Camera selector
        self.camera_combo = QComboBox()
        self.camera_combo.setMinimumWidth(120)
        self.camera_combo.currentIndexChanged.connect(self.on_camera_changed)
        layout.addWidget(self.camera_combo)

        # Start/Stop button
        self.start_stop_btn = QPushButton("Start Camera")
        self.start_stop_btn.setMinimumWidth(100)
        self.start_stop_btn.clicked.connect(self.toggle_camera)
        layout.addWidget(self.start_stop_btn)

        # Status label
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        # Spacer
        layout.addStretch()

        return panel

    def enumerate_cameras(self):
        """Enumerate available cameras."""
        self.camera_combo.clear()
        self.available_cameras = []

        # Test first 10 camera indices
        for i in range(10):
            cap = cv2.VideoCapture(i, cv2.CAP_V4L2)  # Try V4L2 backend first
            if not cap.isOpened():
                cap = cv2.VideoCapture(i)  # Fallback to default backend

            if cap.isOpened():
                # Try to read a frame to verify camera works
                ret, frame = cap.read()
                if ret and frame is not None:
                    self.available_cameras.append(f"Camera {i}")
                cap.release()
            else:
                break

        if not self.available_cameras:
            self.available_cameras = ["No cameras found"]
            self.start_stop_btn.setEnabled(False)

        self.camera_combo.addItems(self.available_cameras)

    def on_camera_changed(self, index):
        """Handle camera selection change."""
        if self.video_thread and self.video_thread.isRunning():
            self.stop_camera()
            self.current_camera = index
            self.start_camera()

    def toggle_camera(self):
        """Toggle camera start/stop."""
        if self.video_thread and self.video_thread.isRunning():
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self):
        """Start the camera and video processing."""
        if self.current_camera >= len(self.available_cameras):
            return

        if self.available_cameras[self.current_camera] == "No cameras found":
            self.status_label.setText("No cameras available")
            return

        self.video_thread = VideoThread(self.current_camera)
        self.video_thread.frame_ready.connect(self.on_frame_ready)
        # Set up QR detection callback
        self.video_thread.qr_scanner.set_qr_callback(self.on_qr_detected)
        self.video_thread.start()

        self.start_stop_btn.setText("Stop Camera")
        self.camera_combo.setEnabled(False)
        self.status_label.setText(f"Camera {self.current_camera} active")

    def stop_camera(self):
        """Stop the camera and video processing."""
        if self.video_thread:
            self.video_thread.stop()
            self.video_thread = None

        self.start_stop_btn.setText("Start Camera")
        self.camera_combo.setEnabled(True)
        self.status_label.setText("Camera stopped")

        # Clear video display
        self.video_widget.clear()

    def on_qr_detected(self, qr_codes):
        """Handle QR code detection."""
        for data, _ in qr_codes:
            if not data:
                continue

            try:
                # Parse QR code data as JSON to extract the ID
                qr_json = json.loads(data)
                subordinate_id = qr_json.get("id")
                if not subordinate_id:
                    self.status_text.append(f"Warning: QR code missing 'id' field: {data}")
                    continue

                if subordinate_id not in self.connected_ids:
                    self.status_text.append(f"QR Code detected with ID: {subordinate_id}")
                    self.status_text.append("Initiating peer connection...")
                    self.coordinator.connect_by_id(subordinate_id)
                    self.connected_ids.add(subordinate_id)
                else:
                    self.status_text.append(f"Already connected to ID: {subordinate_id}")

            except json.JSONDecodeError:
                self.status_text.append(f"Warning: Invalid JSON in QR code: {data}")
                continue
            except Exception as e:
                self.status_text.append(f"Error processing QR code: {e}")
                continue

    def on_frame_ready(self, frame, qr_codes):
        """Handle new frame from video thread."""
        self.video_widget.set_frame(frame, qr_codes)

    def update_ui(self):
        """Update UI elements periodically."""
        # Check for coordinator status updates
        status = self.coordinator.get_status()
        if status:
            status_type, message = status
            self.status_text.append(f"[{status_type.upper()}] {message}")

            # Scroll to bottom to show latest messages
            scrollbar = self.status_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        """Handle application close event."""
        self.stop_camera()
        event.accept()

    def resizeEvent(self, event):
        """Handle window resize event."""
        super().resizeEvent(event)
        # The video widget will automatically redraw with new scaling
