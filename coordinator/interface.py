#!/usr/bin/env python3
"""
Main application window for the Phosaic coordinator GUI.
"""

import asyncio
import sys

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
from components.managers import CameraManager, ConnectionManager, ScreenCaptureManager
from components.screen_capture_widget import ScreenCaptureWidget

from coordinator import Coordinator


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # Initialize Coordinator and Managers
        self.coordinator = Coordinator()
        self.camera_manager = CameraManager()
        self.screen_capture_manager = ScreenCaptureManager()
        self.connection_manager = ConnectionManager(self.coordinator)

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

        # Top control panel
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)

        # Main content area with video feeds
        video_container = self.create_video_display_area()
        main_layout.addWidget(video_container, 1)

        # Status log
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

        # Create camera feed component from the refactored class
        self.camera_interface = CameraInterface()
        layout.addWidget(self.camera_interface, 1)

        # Create screen capture component
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
        self.camera_manager.frame_ready.connect(self.camera_interface.on_frame_ready)
        self.camera_interface.qr_detected.connect(
            self.connection_manager.handle_qr_code_detection
        )

        # Screen capture signals
        self.screen_start_stop_btn.clicked.connect(self.toggle_screen_capture)
        self.screen_capture_manager.frame_ready.connect(
            self.screen_capture_widget.set_frame
        )
        self.screen_capture_manager.error_occurred.connect(self.on_screen_capture_error)

        # Connection signals
        self.connection_manager.status_update.connect(self.append_status_message)

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
        self.status_text.append(message)
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
