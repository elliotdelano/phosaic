#!/usr/bin/env python3
"""
Manager classes for handling camera, screen capture, and connections
in the QR Code Scanner application.
"""

import json

import cv2
from PyQt5.QtCore import QObject, pyqtSignal

from .screen_capture_thread import ScreenCaptureThread
from .video_thread import VideoThread


class CameraManager(QObject):
    """Manages camera operations, including enumeration and video thread."""

    frame_ready = pyqtSignal(object, list)
    cameras_enumerated = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_thread = None
        self.current_camera_index = 0
        self.available_cameras = []

    def enumerate_cameras(self):
        """Enumerate available cameras and emit the list."""
        self.available_cameras = []
        for i in range(10):
            cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap = cv2.VideoCapture(i)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    self.available_cameras.append(f"Camera {i}")
                cap.release()

        if not self.available_cameras:
            self.available_cameras = ["No cameras found"]

        self.cameras_enumerated.emit(self.available_cameras)
        if "No cameras found" not in self.available_cameras[0]:
            try:
                self.current_camera_index = int(self.available_cameras[0].split(" ")[1])
            except (ValueError, IndexError):
                self.current_camera_index = 0

    def set_camera(self, index):
        """Set the current camera based on combo box index."""
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
            self.current_camera_index = camera_id
            self.start_camera()
        else:
            self.current_camera_index = camera_id

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
            return False

        self.video_thread = VideoThread(self.current_camera_index)
        self.video_thread.frame_ready.connect(self.frame_ready.emit)
        self.video_thread.start()
        return True

    def stop_camera(self):
        """Stop the camera and video processing."""
        if self.video_thread:
            self.video_thread.stop()
            self.video_thread = None

    def get_video_thread(self):
        return self.video_thread


class ScreenCaptureManager(QObject):
    """Manages screen capture operations."""

    frame_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.screen_capture_thread = None

    def toggle_screen_capture(self):
        """Toggle screen capture start/stop."""
        if self.screen_capture_thread and self.screen_capture_thread.isRunning():
            self.stop_screen_capture()
        else:
            self.start_screen_capture()

    def start_screen_capture(self):
        """Start the screen capture and processing."""
        self.screen_capture_thread = ScreenCaptureThread()
        self.screen_capture_thread.frame_ready.connect(self.frame_ready.emit)
        self.screen_capture_thread.error_occurred.connect(self.error_occurred.emit)
        self.screen_capture_thread.start()
        return True

    def stop_screen_capture(self):
        """Stop the screen capture and processing."""
        if self.screen_capture_thread:
            self.screen_capture_thread.stop()
            self.screen_capture_thread = None

    def get_screen_size(self):
        """Get the screen size from the screen capture service."""
        if self.screen_capture_thread:
            return self.screen_capture_thread.service.get_screen_size()
        return None
