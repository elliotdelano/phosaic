#!/usr/bin/env python3
"""
VideoFileThread for reading frames from a video file for UI preview.
"""

import time

import cv2
from PyQt6.QtCore import QThread, pyqtSignal, QWaitCondition, QMutex


class VideoFileThread(QThread):
    """
    Thread for reading frames from a video file and emitting them via PyQt signals.
    Used for UI preview of video file playback.
    """

    frame_ready = pyqtSignal(object)  # frame
    error_occurred = pyqtSignal(str)  # error message

    def __init__(self, video_file_path, fps=None, loop_video=True):
        super().__init__()
        self.video_file_path = video_file_path
        self.fps = fps
        self.loop_video = loop_video
        self.running = False
        self.cap = None
        self.mutex = QMutex()
        self.condition = QWaitCondition()
        self.frame_width = None
        self.frame_height = None

    def run(self):
        """Main thread loop for reading frames from video file."""
        self.running = True

        try:
            # Open video file
            self.cap = cv2.VideoCapture(self.video_file_path)
            if not self.cap.isOpened():
                error_msg = f"Failed to open video file: {self.video_file_path}"
                self.error_occurred.emit(error_msg)
                return

            # Get video properties
            video_fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            # Use video FPS if not specified
            if self.fps is None:
                self.fps = video_fps if video_fps > 0 else 30

            frame_time = 1.0 / self.fps
            sleep_ms = int(frame_time * 1000)

            while self.running:
                try:
                    ret, frame = self.cap.read()

                    if not ret:
                        # End of video
                        if self.loop_video:
                            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            continue
                        else:
                            self.error_occurred.emit("End of video reached")
                            break

                    if frame is not None and frame.size > 0:
                        # Emit the frame
                        self.frame_ready.emit(frame)

                    # Wait to maintain the desired FPS (interruptible)
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
                    print(f"Error reading video frame: {error_str}")
                    self.error_occurred.emit(f"Error reading video frame: {error_str}")
                    time.sleep(0.1)

        except Exception as e:
            error_str = str(e)
            self.error_occurred.emit(f"Error opening video file: {error_str}")
        finally:
            if self.cap:
                self.cap.release()
                self.cap = None

    def stop(self):
        """Stop the video file thread."""
        self.running = False
        # Wake up the thread if it's waiting
        self.mutex.lock()
        self.condition.wakeAll()
        self.mutex.unlock()
        if self.cap:
            self.cap.release()
            self.cap = None
        self.wait()

