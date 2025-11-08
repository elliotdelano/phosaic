#!/usr/bin/env python3
"""
VideoWidget component for displaying camera feed with QR code annotations.
"""

import json

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QSizePolicy, QWidget


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
        q_image = QImage(
            rgb_frame.data, width, height, bytes_per_line, QImage.Format_RGB888
        )

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
        scaled_pixmap = self.pixmap.scaled(
            widget_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        # Calculate position to center the image
        x = (widget_rect.width() - scaled_pixmap.width()) // 2
        y = (widget_rect.height() - scaled_pixmap.height()) // 2

        # Draw the scaled pixmap centered in the widget
        painter.drawPixmap(x, y, scaled_pixmap)

        # Draw QR code annotations if any exist
        if self.qr_codes and self.current_frame is not None:
            self.draw_qr_annotations(
                painter, x, y, scaled_pixmap.width(), scaled_pixmap.height()
            )

    def draw_qr_annotations(
        self, painter, offset_x, offset_y, display_width, display_height
    ):
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
                    painter.drawLine(
                        start_point[0], start_point[1], end_point[0], end_point[1]
                    )

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

                # Try to parse ID from JSON for display
                display_text = data
                try:
                    qr_json = json.loads(data)
                    if "id" in qr_json:
                        display_text = f"ID: {qr_json['id']}"
                except (json.JSONDecodeError, TypeError):
                    pass  # Fall back to raw data if parsing fails

                text = f"QR{i + 1}: {display_text[:15]}{'...' if len(display_text) > 15 else ''}"
                painter.drawText(center_x - 50, center_y - 10, text)

    def clear(self):
        """Clear the current frame."""
        self.current_frame = None
        self.pixmap = None
        self.qr_codes = []
        self.update()
