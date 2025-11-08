import threading
import time

import cv2
import numpy as np
from mss import mss


class VideoSource(threading.Thread):
    """Abstract base class for video sources."""

    def __init__(self, video_track, loop):
        super().__init__()
        self.video_track = video_track
        self.loop = loop
        self.running = False
        self.daemon = True

    def run(self):
        """Main loop for the video source."""
        raise NotImplementedError("This method should be overridden by subclasses")

    def stop(self):
        """Stops the video source loop."""
        self.running = False


class ScreenCaptureSource(VideoSource):
    """Video source that captures the screen."""

    def __init__(self, video_track, loop, fps=30):
        super().__init__(video_track, loop)
        self.fps = fps

    def run(self):
        """Captures the screen and sends frames to the video track."""
        self.running = True
        with mss() as sct:
            # Use the first monitor
            monitor = sct.monitors[1]
            while self.running:
                # Grab the data
                sct_img = sct.grab(monitor)

                # Convert to a numpy array and then to BGR format for OpenCV
                frame = np.array(sct_img)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                # Add frame to the video track if the loop is running
                if self.video_track and self.loop and self.loop.is_running():
                    self.loop.call_soon_threadsafe(self.video_track.add_frame, frame)

                # Wait to maintain the desired FPS
                time.sleep(1 / self.fps)
