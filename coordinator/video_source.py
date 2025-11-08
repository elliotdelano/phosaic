import logging
import os
import threading
import time

import cv2
import numpy as np
from mss import mss

# Setup logger for this module
logger = logging.getLogger(__name__)


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
    """Video source that captures the screen using robust logic."""

    def __init__(self, video_track, loop, fps=30):
        super().__init__(video_track, loop)
        self.fps = fps

    def run(self):
        """Captures the screen and sends frames to the video track."""
        self.running = True
        logger.info("--- ScreenCaptureSource thread started ---")

        # Robust environment checks for Linux
        display = os.environ.get("DISPLAY")
        xdg_session = os.environ.get("XDG_SESSION_TYPE", "").lower()

        if not display and os.name != "nt":
            error_msg = (
                "DISPLAY environment variable not set. "
                "Screen capture requires X11 display access."
            )
            logger.error(error_msg)
            logger.info("--- ScreenCaptureSource thread exiting ---")
            return

        if xdg_session == "wayland" and display:
            logger.warning(
                f"Wayland session detected, but DISPLAY={display} is set. "
                "Attempting to use X11/XWayland compatibility layer."
            )

        try:
            # Use context manager for proper resource management
            with mss() as sct:
                # Validate monitors
                if not sct.monitors or len(sct.monitors) == 0:
                    logger.error("No monitors detected for screen capture.")
                    logger.info("--- ScreenCaptureSource thread exiting ---")
                    return

                # Use the primary monitor (index 1)
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]

                if "width" not in monitor or "height" not in monitor:
                    logger.error("Invalid monitor configuration detected.")
                    logger.info("--- ScreenCaptureSource thread exiting ---")
                    return

                logger.info(
                    f"Screen capture initialized: {monitor['width']}x{monitor['height']} "
                    f"(DISPLAY={display})"
                )

                while self.running:
                    try:
                        # Grab screen data
                        sct_img = sct.grab(monitor)

                        if sct_img is None:
                            time.sleep(0.1)  # Wait before retrying
                            continue

                        # Convert to numpy array
                        frame = np.array(sct_img)

                        if frame.size == 0:
                            continue

                        # Convert BGRA to BGR for aiortc/OpenCV compatibility
                        if len(frame.shape) == 3 and frame.shape[2] == 4:
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                            # Ensure frame is contiguous
                            frame = np.ascontiguousarray(frame)

                            logger.debug(
                                "ScreenCaptureSource: Frame captured and converted."
                            )

                            if (
                                self.video_track
                                and self.loop
                                and self.loop.is_running()
                            ):
                                logger.debug(
                                    "ScreenCaptureSource: Pushing frame to video track."
                                )

                                if (
                                    self.video_track
                                    and self.loop
                                    and self.loop.is_running()
                                ):
                                    logger.debug(
                                        "ScreenCaptureSource: Pushing frame to video track."
                                    )

                                    self.loop.call_soon_threadsafe(
                                        self.video_track.add_frame, frame
                                    )

                        # Maintain FPS
                        time.sleep(1 / self.fps)

                    except Exception as e:
                        logger.error(f"Error in screen capture loop: {e}")
                        time.sleep(0.5)  # Pause before retrying

        except Exception as e:
            logger.error(f"Failed to initialize screen capture: {e}")

        logger.info("--- ScreenCaptureSource thread finished ---")
