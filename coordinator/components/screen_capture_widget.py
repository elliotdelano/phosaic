#!/usr/bin/env python3
"""
ScreenCaptureWidget component for displaying screen capture feed.
"""

import cv2
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget


class ScreenCaptureWidget(QWidget):
    """Custom widget for displaying screen capture feed with responsive scaling."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.current_frame = None
        self.pixmap = None

    def set_frame(self, frame):
        """Set the frame to display."""
        if frame is None or frame.size == 0:
            return

        try:
            # Ensure frame is valid numpy array with proper shape
            if not isinstance(frame, np.ndarray) or len(frame.shape) != 3:
                return

            height, width = frame.shape[:2]
            if height == 0 or width == 0:
                return

            self.current_frame = frame

            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Ensure frame is contiguous in memory for QImage
            rgb_frame = np.ascontiguousarray(rgb_frame)

            # Create QImage from frame (make a copy to ensure data remains valid)
            height, width, channel = rgb_frame.shape
            bytes_per_line = 3 * width
            # Create a copy of the data to ensure QImage has its own copy
            rgb_data = rgb_frame.copy()
            q_image = QImage(
                rgb_data.data, width, height, bytes_per_line, QImage.Format.Format_RGB888
            )

            # Ensure the image is valid
            if q_image.isNull():
                return

            # Create pixmap and scale it to fit widget while maintaining aspect ratio
            self.pixmap = QPixmap.fromImage(q_image)
            if self.pixmap.isNull():
                return

            self.update()
        except Exception as e:
            print(f"Error setting frame: {e}")
            return

    def paintEvent(self, event):
        """Override paint event to draw the scaled screen capture frame."""
        if not self.pixmap:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Get widget dimensions
        widget_rect = self.rect()

        # Scale pixmap to fit widget while maintaining aspect ratio
        scaled_pixmap = self.pixmap.scaled(
            widget_rect.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )

        # Calculate position to center the image
        x = (widget_rect.width() - scaled_pixmap.width()) // 2
        y = (widget_rect.height() - scaled_pixmap.height()) // 2

        # Draw the scaled pixmap centered in the widget
        painter.drawPixmap(x, y, scaled_pixmap)

    def clear(self):
        """Clear the current frame."""
        self.current_frame = None
        self.pixmap = None
        self.update()
