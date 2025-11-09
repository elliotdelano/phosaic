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
    QComboBox,
    QFileDialog,
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
from components.managers import (
    CameraManager,
    ConnectionManager,
    ScreenCaptureManager,
    VideoFileManager,
)
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
        self.video_file_manager = VideoFileManager()
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
        group = QGroupBox("Video Source")
        layout = QVBoxLayout(group)
        
        # Source type selection
        source_type_layout = QHBoxLayout()
        source_type_layout.addWidget(QLabel("Source Type:"))
        self.source_type_combo = QComboBox()
        self.source_type_combo.addItems(["Screen Capture", "Video File"])
        self.source_type_combo.currentIndexChanged.connect(self.on_source_type_changed)
        source_type_layout.addWidget(self.source_type_combo)
        source_type_layout.addStretch()
        layout.addLayout(source_type_layout)
        
        # Video file selection (initially hidden)
        video_file_layout = QHBoxLayout()
        video_file_layout.addWidget(QLabel("Video File:"))
        self.video_file_label = QLabel("No file selected")
        self.video_file_label.setStyleSheet("color: gray;")
        video_file_layout.addWidget(self.video_file_label, 1)
        self.select_video_file_btn = QPushButton("Browse...")
        self.select_video_file_btn.clicked.connect(self.select_video_file)
        video_file_layout.addWidget(self.select_video_file_btn)
        self.video_file_layout_widget = QWidget()
        self.video_file_layout_widget.setLayout(video_file_layout)
        self.video_file_layout_widget.setVisible(False)
        layout.addWidget(self.video_file_layout_widget)
        
        # Start/Stop button
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
        
        # Video file signals
        self.video_file_manager.frame_ready.connect(
            self.screen_capture_widget.set_frame
        )
        self.video_file_manager.error_occurred.connect(self.on_video_file_error)

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

    def on_source_type_changed(self, index):
        """Handle source type selection change."""
        source_type = "screen" if index == 0 else "file"
        
        # Update UI visibility
        self.video_file_layout_widget.setVisible(index == 1)
        
        # Update button text
        if index == 0:
            self.screen_start_stop_btn.setText("Start Screen Capture")
        else:
            self.screen_start_stop_btn.setText("Start Video File")
        
        # If switching to file source, check if file is selected
        if index == 1 and self.video_file_label.text() == "No file selected":
            self.append_status_message("Please select a video file before starting")
        
        # Update coordinator if there are active connections
        if self.coordinator.connections:
            video_file_path = None
            if source_type == "file":
                file_path = self.video_file_label.text()
                if file_path != "No file selected":
                    video_file_path = file_path
            
            if video_file_path or source_type == "screen":
                success = self.coordinator.set_video_source_type(source_type, video_file_path)
                if success:
                    self.append_status_message(f"Video source switched to: {source_type}")
                else:
                    self.append_status_message(f"Failed to switch video source to: {source_type}")

    def select_video_file(self):
        """Open file dialog to select video file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.webm *.flv *.wmv);;All Files (*)"
        )
        if file_path:
            self.video_file_label.setText(file_path)
            self.video_file_label.setStyleSheet("")
            self.append_status_message(f"Video file selected: {file_path}")
            
            # Update video file manager
            self.video_file_manager.set_video_file(file_path)
            
            # If coordinator is already using file source, update it
            if self.coordinator._video_source_type == "file" and self.coordinator.connections:
                success = self.coordinator.set_video_source_type("file", file_path)
                if success:
                    self.append_status_message("Video source updated with new file")
                else:
                    self.append_status_message("Failed to update video source with new file")
            
            # If video file preview is running, restart it with new file
            if (self.video_file_manager.video_file_thread 
                and self.video_file_manager.video_file_thread.isRunning()):
                self.video_file_manager.stop_video_file()
                self.video_file_manager.start_video_file()

    def toggle_screen_capture(self):
        """Toggle screen capture/video file and update UI."""
        source_type_index = self.source_type_combo.currentIndex()
        source_type = "screen" if source_type_index == 0 else "file"
        
        # Validate file selection for file source
        if source_type == "file":
            file_path = self.video_file_label.text()
            if file_path == "No file selected":
                self.append_status_message("Please select a video file first")
                return
        
        # Set video source type in coordinator if needed
        if source_type == "file":
            file_path = self.video_file_label.text()
            self.coordinator.set_video_source_type(source_type, file_path)
        else:
            self.coordinator.set_video_source_type(source_type)
        
        # Toggle appropriate manager for UI preview
        is_running = False
        if source_type == "screen":
            # Stop video file if running
            if self.video_file_manager.video_file_thread and self.video_file_manager.video_file_thread.isRunning():
                self.video_file_manager.stop_video_file()
            
            # Toggle screen capture
            self.screen_capture_manager.toggle_screen_capture()
            is_running = (
                self.screen_capture_manager.screen_capture_thread
                and self.screen_capture_manager.screen_capture_thread.isRunning()
            )
        else:
            # Stop screen capture if running
            if self.screen_capture_manager.screen_capture_thread and self.screen_capture_manager.screen_capture_thread.isRunning():
                self.screen_capture_manager.stop_screen_capture()
            
            # Set video file path and toggle
            file_path = self.video_file_label.text()
            self.video_file_manager.set_video_file(file_path)
            self.video_file_manager.toggle_video_file()
            is_running = (
                self.video_file_manager.video_file_thread
                and self.video_file_manager.video_file_thread.isRunning()
            )
        
        # Update button text
        if source_type_index == 0:
            self.screen_start_stop_btn.setText(
                "Stop Screen Capture" if is_running else "Start Screen Capture"
            )
            self.status_label.setText(
                "Screen capture active" if is_running else "Screen capture stopped"
            )
        else:
            self.screen_start_stop_btn.setText(
                "Stop Video File" if is_running else "Start Video File"
            )
            self.status_label.setText(
                "Video file active" if is_running else "Video file stopped"
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

    def on_video_file_error(self, error_message):
        """Handle error from video file thread."""
        self.append_status_message(f"[ERROR] Video File: {error_message}")
        self.status_label.setText("Video file error")
        if (
            self.video_file_manager.video_file_thread
            and self.video_file_manager.video_file_thread.isRunning()
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
        self.video_file_manager.stop_video_file()

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
