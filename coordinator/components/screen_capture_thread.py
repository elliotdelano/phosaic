#!/usr/bin/env python3
"""
ScreenCaptureThread for consuming screen frames from the centralized service.
"""

import time

from PyQt5.QtCore import QThread, pyqtSignal, QWaitCondition, QMutex

from .screen_capture_service import ScreenCaptureService


class ScreenCaptureThread(QThread):
    """
    Thread for consuming screen frames from the centralized ScreenCaptureService.
    This thread reads frames from the service buffer and emits them via PyQt signals.
    """

    frame_ready = pyqtSignal(object)  # frame
    error_occurred = pyqtSignal(str)  # error message

    def __init__(self, fps=30):
        super().__init__()
        self.fps = fps
        self.running = False
        self.service = ScreenCaptureService()
        self.mutex = QMutex()
        self.condition = QWaitCondition()

    def run(self):
        """Main thread loop for consuming frames from the service."""
        self.running = True

        # Start the centralized service if not already running
        if not self.service.is_running():
            # Set up error callback to emit via signal
            def error_callback(error_msg):
                self.error_occurred.emit(error_msg)

            self.service.start(fps=self.fps, error_callback=error_callback)

        frame_time = 1.0 / self.fps
        sleep_ms = int(frame_time * 1000)

        while self.running:
            try:
                # Get the latest frame from the centralized service
                frame = self.service.get_latest_frame()

                if frame is not None and frame.size > 0:
                    # Emit the frame
                    self.frame_ready.emit(frame)

                # Wait to maintain the desired FPS (interruptible)
                # Break sleep into smaller chunks to check running flag more frequently
                elapsed = 0
                chunk_ms = 10  # Check every 10ms
                while elapsed < sleep_ms and self.running:
                    self.mutex.lock()
                    remaining = min(chunk_ms, sleep_ms - elapsed)
                    self.condition.wait(self.mutex, remaining)
                    self.mutex.unlock()
                    elapsed += chunk_ms

            except Exception as e:
                error_str = str(e)
                print(f"Error consuming screen frame: {error_str}")
                self.error_occurred.emit(f"Error consuming screen frame: {error_str}")
                # Wait a bit before retrying
                time.sleep(0.1)

    def stop(self):
        """Stop the screen capture thread."""
        self.running = False
        # Wake up the thread if it's waiting
        self.mutex.lock()
        self.condition.wakeAll()
        self.mutex.unlock()
        self.wait()
        # Note: We don't stop the service here as other consumers may be using it
