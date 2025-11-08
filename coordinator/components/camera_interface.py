#!/usr/bin/env python3
"""
CameraInterface main window component for QR Code Scanner application.
"""

import json
import os
import sys

import cv2
from PyQt5.QtCore import Qt, QTimer
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

from .screen_capture_thread import ScreenCaptureThread
from .screen_capture_widget import ScreenCaptureWidget
from .video_thread import VideoThread
from .video_widget import VideoWidget

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from coordinator import Coordinator


class CameraInterface(QMainWindow):
    """Main window for camera interface with selector and feed display."""

    def __init__(self):
        super().__init__()
        self.video_thread = None
        self.screen_capture_thread = None
        self.current_camera = 0
        self.available_cameras = []
        self.coordinator = Coordinator()
        self.connected_ids = set()  # Track IDs we've already connected to

        self.init_ui()
        self.enumerate_cameras()

        if (
            self.available_cameras
            and "No cameras found" not in self.available_cameras[0]
        ):
            try:
                self.current_camera = int(self.available_cameras[0].split(" ")[1])
            except (ValueError, IndexError):
                pass

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
        video_container = self.create_video_display_area()
        main_layout.addWidget(video_container, 1)  # Give it stretch factor of 1

        # Status display area
        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(150)
        self.status_text.setReadOnly(True)
        self.status_text.append("Ready to scan QR codes for peer connections...")
        main_layout.addWidget(self.status_text)

    def create_control_panel(self):
        """Create the top control panel."""
        panel = QWidget()
        panel.setMaximumHeight(40)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)

        # Status label
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        # Spacer
        layout.addStretch()

        return panel

    def create_video_display_area(self):
        """Create the video display area with camera and screen capture widgets."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Camera video widget
        camera_group = self.create_display_group("Camera Feed", "camera")
        self.video_widget = VideoWidget()
        camera_group.layout().addWidget(self.video_widget)
        layout.addWidget(camera_group, 1)

        # Screen capture widget
        screen_group = self.create_display_group("Screen Capture", "screen")
        self.screen_capture_widget = ScreenCaptureWidget()
        screen_group.layout().addWidget(self.screen_capture_widget)
        layout.addWidget(screen_group, 1)

        return container

    def create_display_group(self, title, widget_type):
        """Create a display group with title and control buttons."""
        from PyQt5.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QVBoxLayout

        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(5, 5, 5, 5)

        # Control buttons layout
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)

        if widget_type == "camera":
            # Camera controls
            self.camera_start_stop_btn = QPushButton("Start Camera")
            self.camera_start_stop_btn.setMinimumWidth(100)
            self.camera_start_stop_btn.clicked.connect(self.toggle_camera)
            controls_layout.addWidget(self.camera_start_stop_btn)

            # Camera selector
            controls_layout.addWidget(QLabel("Camera:"))
            self.camera_combo = QComboBox()
            self.camera_combo.setMinimumWidth(80)
            self.camera_combo.currentIndexChanged.connect(self.on_camera_changed)
            controls_layout.addWidget(self.camera_combo)

        elif widget_type == "screen":
            # Screen capture controls
            self.screen_start_stop_btn = QPushButton("Start Screen Capture")
            self.screen_start_stop_btn.setMinimumWidth(130)
            self.screen_start_stop_btn.clicked.connect(self.toggle_screen_capture)
            controls_layout.addWidget(self.screen_start_stop_btn)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        return group

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

        if not self.available_cameras:
            self.available_cameras = ["No cameras found"]
            self.camera_start_stop_btn.setEnabled(False)

        self.camera_combo.addItems(self.available_cameras)

    def on_camera_changed(self, index):
        """Handle camera selection change."""
        if index < 0 or index >= len(self.available_cameras):
            return

        camera_string = self.available_cameras[index]
        if "No cameras found" in camera_string:
            return

        try:
            camera_id = int(camera_string.split(" ")[1])
        except (IndexError, ValueError):
            return

        if self.video_thread and self.video_thread.isRunning():
            self.stop_camera()
            self.current_camera = camera_id
            self.start_camera()
        else:
            self.current_camera = camera_id

    def toggle_screen_capture(self):
        """Toggle screen capture start/stop."""
        if self.screen_capture_thread and self.screen_capture_thread.isRunning():
            self.stop_screen_capture()
        else:
            self.start_screen_capture()

    def toggle_camera(self):
        """Toggle camera start/stop."""
        if self.video_thread and self.video_thread.isRunning():
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self):
        """Start the camera and video processing."""
        if (
            not self.available_cameras
            or "No cameras found" in self.available_cameras[0]
        ):
            self.status_label.setText("No cameras available")
            return

        self.video_thread = VideoThread(self.current_camera)
        self.video_thread.frame_ready.connect(self.on_frame_ready)
        # Set up QR detection callback
        self.video_thread.qr_scanner.set_qr_callback(self.on_qr_detected)
        self.video_thread.start()

        self.camera_start_stop_btn.setText("Stop Camera")
        self.camera_combo.setEnabled(False)
        self.status_label.setText(f"Camera {self.current_camera} active")

    def stop_camera(self):
        """Stop the camera and video processing."""
        if self.video_thread:
            self.video_thread.stop()
            self.video_thread = None

        self.camera_start_stop_btn.setText("Start Camera")
        self.camera_combo.setEnabled(True)
        self.status_label.setText("Camera stopped")

        # Clear video display
        self.video_widget.clear()

    def start_screen_capture(self):
        """Start the screen capture and processing."""
        self.screen_capture_thread = ScreenCaptureThread()
        self.screen_capture_thread.frame_ready.connect(self.on_screen_frame_ready)
        self.screen_capture_thread.error_occurred.connect(self.on_screen_capture_error)
        self.screen_capture_thread.start()

        self.screen_start_stop_btn.setText("Stop Screen Capture")
        self.status_label.setText("Screen capture active")

    def stop_screen_capture(self):
        """Stop the screen capture and processing."""
        if self.screen_capture_thread:
            self.screen_capture_thread.stop()
            self.screen_capture_thread = None

        self.screen_start_stop_btn.setText("Start Screen Capture")
        self.status_label.setText("Screen capture stopped")

        # Clear screen capture display
        self.screen_capture_widget.clear()

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
                    self.status_text.append(
                        f"Warning: QR code missing 'id' field: {data}"
                    )
                    continue

                if subordinate_id not in self.connected_ids:
                    self.status_text.append(
                        f"QR Code detected with ID: {subordinate_id}"
                    )
                    self.status_text.append("Initiating peer connection...")
                    self.coordinator.connect_by_id(subordinate_id)
                    self.connected_ids.add(subordinate_id)
                else:
                    self.status_text.append(
                        f"Already connected to ID: {subordinate_id}"
                    )

            except json.JSONDecodeError:
                self.status_text.append(f"Warning: Invalid JSON in QR code: {data}")
                continue
            except Exception as e:
                self.status_text.append(f"Error processing QR code: {e}")
                continue

    def on_screen_frame_ready(self, frame):
        """Handle new frame from screen capture thread."""
        if frame is not None and frame.size > 0:
            self.screen_capture_widget.set_frame(frame)

    def on_screen_capture_error(self, error_message):
        """Handle error from screen capture thread."""
        self.status_text.append(f"[ERROR] Screen Capture: {error_message}")
        self.status_label.setText("Screen capture error")
        # Auto-stop on error
        self.stop_screen_capture()

        # Scroll to bottom to show latest messages
        scrollbar = self.status_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

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
        self.stop_screen_capture()
        event.accept()

    def resizeEvent(self, event):
        """Handle window resize event."""
        super().resizeEvent(event)
        # The video widget will automatically redraw with new scaling
