#!/usr/bin/env python3
"""
Main application window for the Phosaic coordinator GUI.
"""

import asyncio
import json
import sys
import cv2
import numpy as np
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Add project root to path to allow sibling imports
sys.path.append(sys.path[0] + "/..")

from components.camera_interface import CameraInterface
from components.managers import CameraManager, ScreenCaptureManager
from components.screen_capture_widget import ScreenCaptureWidget
from projection import ProjectionMapper

from coordinator import Coordinator


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # Initialize Core Components
        self.coordinator = Coordinator()
        self.camera_manager = CameraManager()
        self.screen_capture_manager = ScreenCaptureManager()
        self.connected_ids = set()

        self.init_ui()
        self.connect_signals()

        # Initial setup
        self.coordinator.start()
        self.camera_manager.enumerate_cameras()

        # Set up timer for coordinator status updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_coordinator_status)
        self.timer.start(100)

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Phosaic Coordinator")
        self.setGeometry(100, 100, 1000, 700)
        self.setMinimumSize(600, 400)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)

        video_container = self.create_video_display_area()
        main_layout.addWidget(video_container, 1)

        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(150)
        self.status_text.setReadOnly(True)
        self.append_status_message("Ready to scan QR codes for peer connections...")
        main_layout.addWidget(self.status_text)

    def create_control_panel(self):
        """Create the top control panel."""
        panel = QWidget()
        panel.setMaximumHeight(40)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)
        layout.addStretch()
        return panel

    def create_video_display_area(self):
        """Create the area for video feeds."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.camera_interface = CameraInterface()
        layout.addWidget(self.camera_interface, 1)

        self.screen_capture_group = self.create_screen_capture_group()
        layout.addWidget(self.screen_capture_group, 1)

        return container

    def create_screen_capture_group(self):
        """Create the screen capture group widget."""
        group = QGroupBox("Screen Capture")
        layout = QVBoxLayout(group)
        controls_layout = QHBoxLayout()

        self.screen_start_stop_btn = QPushButton("Start Screen Capture")
        controls_layout.addWidget(self.screen_start_stop_btn)
        controls_layout.addStretch()

        self.screen_capture_widget = ScreenCaptureWidget()
        layout.addLayout(controls_layout)
        layout.addWidget(self.screen_capture_widget)
        return group

    def connect_signals(self):
        """Connect signals from managers and UI components."""
        # Camera signals
        self.camera_interface.toggle_camera_clicked.connect(self.toggle_camera)
        self.camera_interface.camera_selection_changed.connect(
            self.camera_manager.set_camera
        )
        self.camera_manager.cameras_enumerated.connect(
            self.camera_interface.on_cameras_enumerated
        )
        self.camera_manager.frame_ready.connect(self.on_camera_frame_ready)

        # Screen capture signals
        self.screen_start_stop_btn.clicked.connect(self.toggle_screen_capture)
        self.screen_capture_manager.frame_ready.connect(
            self.screen_capture_widget.set_frame
        )
        self.screen_capture_manager.error_occurred.connect(self.on_screen_capture_error)

    def on_camera_frame_ready(self, frame, qr_codes):
        """Handle new frame from camera, display it, and process QR codes."""
        # Display the camera feed
        self.camera_interface.on_frame_ready(frame, qr_codes)

        # Process QR codes for projection mapping
        if not qr_codes:
            return

        for data, points in qr_codes:
            if not data:
                continue

            try:
                qr_json = json.loads(data)
                subordinate_id = qr_json.get("id")
                if not subordinate_id:
                    self.append_status_message(
                        f"Warning: QR code missing 'id' field: {data}"
                    )
                    continue

                if subordinate_id in self.connected_ids:
                    continue

                self.append_status_message(f"New QR code detected: {subordinate_id}")

                screen_size = self.screen_capture_manager.get_screen_size()
                if not screen_size:
                    self.append_status_message(
                        "[ERROR] Screen size not available. Is screen capture running?"
                    )
                    continue

                camera_height, camera_width, _ = frame.shape
                camera_size = (camera_width, camera_height)

                mapper = ProjectionMapper(screen_size, camera_size)
                screen_points = mapper.map_points(points)

                # Define the destination rectangle (default 640x480, configurable)
                output_size = (640, 480)  # (width, height)
                dst_rect = np.float32([
                    [0, 0],
                    [output_size[0], 0],
                    [output_size[0], output_size[1]],
                    [0, output_size[1]]
                ])

                # Ensure screen_points is in the right shape (4, 2)
                if screen_points is None or screen_points.shape[0] != 4:
                    self.append_status_message(
                        f"[ERROR] Could not calculate a valid projection for {subordinate_id} (need 4 points)"
                    )
                    continue
                if len(screen_points.shape) == 3:
                    screen_points = np.squeeze(screen_points, axis=1)

                # Calculate the perspective transform matrix
                warp_matrix = cv2.getPerspectiveTransform(np.float32(screen_points), dst_rect)

                self.append_status_message(
                    f"Calculated perspective warp for {subordinate_id}."
                )
                self.append_status_message(
                    f"Initiating connection to {subordinate_id}..."
                )

                self.coordinator.connect_by_id(subordinate_id, warp_matrix=warp_matrix, output_size=output_size)
                self.connected_ids.add(subordinate_id)

            except json.JSONDecodeError:
                self.append_status_message(f"Warning: Invalid JSON in QR code: {data}")
                continue
            except Exception as e:
                self.append_status_message(f"Error processing QR code: {e}")
                continue

    def toggle_camera(self):
        """Toggle camera and update UI."""
        self.camera_manager.toggle_camera()
        is_running = (
            self.camera_manager.video_thread
            and self.camera_manager.video_thread.isRunning()
        )
        self.camera_interface.set_running_state(is_running)
        self.status_label.setText("Camera active" if is_running else "Camera stopped")

    def toggle_screen_capture(self):
        """Toggle screen capture and update UI."""
        self.screen_capture_manager.toggle_screen_capture()
        is_running = (
            self.screen_capture_manager.screen_capture_thread
            and self.screen_capture_manager.screen_capture_thread.isRunning()
        )
        self.screen_start_stop_btn.setText(
            "Stop Screen Capture" if is_running else "Start Screen Capture"
        )
        self.status_label.setText(
            "Screen capture active" if is_running else "Screen capture stopped"
        )
        if not is_running:
            self.screen_capture_widget.clear()

    def on_screen_capture_error(self, error_message):
        """Handle error from screen capture thread."""
        self.append_status_message(f"[ERROR] Screen Capture: {error_message}")
        self.status_label.setText("Screen capture error")
        if (
            self.screen_capture_manager.screen_capture_thread
            and self.screen_capture_manager.screen_capture_thread.isRunning()
        ):
            self.toggle_screen_capture()

    def update_coordinator_status(self):
        """Update UI with status from coordinator."""
        status = self.coordinator.get_status()
        if status:
            status_type, message = status
            self.append_status_message(f"[{status_type.upper()}] {message}")

    def append_status_message(self, message):
        """Append a message to the status text box."""
        self.status_text.append(str(message))
        scrollbar = self.status_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event):
        """Handle application close event."""
        self.camera_manager.stop_camera()
        self.screen_capture_manager.stop_screen_capture()

        if self.coordinator.loop and self.coordinator.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self.coordinator.shutdown(), self.coordinator.loop
            )
            try:
                future.result(timeout=2)
            except Exception as e:
                print(f"Error shutting down coordinator: {e}")

        if self.coordinator.webrtc_thread:
            self.coordinator.webrtc_thread.join(timeout=2)

        event.accept()


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
