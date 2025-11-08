#!/usr/bin/env python3
"""
Qt-based GUI interface for QR Code Scanner
Provides a responsive window with camera selector and live camera feed display.
"""

import sys
import cv2
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QComboBox, QPushButton,
                             QSplitter, QFrame, QSizePolicy, QTextEdit)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal, QRect

from coordinator import Coordinator
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


class VideoWidget(QWidget):
    """Custom widget for displaying video feed with responsive scaling and QR code annotations."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.current_frame = None
        self.pixmap = None
        self.qr_codes = []

    def set_frame(self, frame, qr_codes=None):
        """Set the frame and QR codes to display."""
        self.current_frame = frame
        self.qr_codes = qr_codes or []

        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Create QImage from frame
        height, width, channel = rgb_frame.shape
        bytes_per_line = 3 * width
        q_image = QImage(rgb_frame.data, width, height, bytes_per_line, QImage.Format_RGB888)

        # Create pixmap and scale it to fit widget while maintaining aspect ratio
        self.pixmap = QPixmap.fromImage(q_image)
        self.update()

    def paintEvent(self, event):
        """Override paint event to draw the scaled video frame with QR code annotations."""
        if not self.pixmap:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Get widget dimensions
        widget_rect = self.rect()

        # Scale pixmap to fit widget while maintaining aspect ratio
        scaled_pixmap = self.pixmap.scaled(widget_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # Calculate position to center the image
        x = (widget_rect.width() - scaled_pixmap.width()) // 2
        y = (widget_rect.height() - scaled_pixmap.height()) // 2

        # Draw the scaled pixmap centered in the widget
        painter.drawPixmap(x, y, scaled_pixmap)

        # Draw QR code annotations if any exist
        if self.qr_codes and self.current_frame is not None:
            self.draw_qr_annotations(painter, x, y, scaled_pixmap.width(), scaled_pixmap.height())

    def draw_qr_annotations(self, painter, offset_x, offset_y, display_width, display_height):
        """Draw QR code bounding boxes and information overlays."""
        if not self.current_frame is not None:
            return

        frame_height, frame_width = self.current_frame.shape[:2]

        # Calculate scaling factors
        scale_x = display_width / frame_width
        scale_y = display_height / frame_height

        for i, (data, points) in enumerate(self.qr_codes):
            if points is not None:
                # Scale points to match displayed pixmap
                scaled_points = []
                for point in points:
                    x = int(point[0] * scale_x) + offset_x
                    y = int(point[1] * scale_y) + offset_y
                    scaled_points.append((x, y))

                # Draw quadrilateral outline
                painter.setPen(QPen(QColor(0, 255, 0), 2))
                for j in range(len(scaled_points)):
                    start_point = scaled_points[j]
                    end_point = scaled_points[(j + 1) % len(scaled_points)]
                    painter.drawLine(start_point[0], start_point[1], end_point[0], end_point[1])

                # Draw corner points
                painter.setPen(QPen(QColor(0, 0, 255), 5))
                for point in scaled_points:
                    painter.drawEllipse(point[0] - 2, point[1] - 2, 4, 4)

                # Calculate center point for text
                center_x = int(sum(p[0] for p in scaled_points) / len(scaled_points))
                center_y = int(sum(p[1] for p in scaled_points) / len(scaled_points))

                # Draw QR code info
                font = painter.font()
                font.setPointSize(8)
                painter.setFont(font)
                painter.setPen(QPen(QColor(255, 255, 255)))

                text = f"QR{i+1}: {data[:15]}{'...' if len(data) > 15 else ''}"
                painter.drawText(center_x - 50, center_y - 10, text)

    def clear(self):
        """Clear the current frame."""
        self.current_frame = None
        self.pixmap = None
        self.qr_codes = []
        self.update()


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
            if data and data not in self.connected_ids:
                self.status_text.append(f"QR Code detected: {data}")
                self.status_text.append("Initiating peer connection...")
                self.coordinator.connect_by_id(data)
                self.connected_ids.add(data)

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
