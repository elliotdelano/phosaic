import logging
import threading
import time

# Setup logger for this module
logger = logging.getLogger(__name__)

# Import the centralized screen capture service
# Use relative import if in same package, or absolute if needed
try:
    from components.screen_capture_service import ScreenCaptureService
except ImportError:
    # Fallback for different import paths
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from components.screen_capture_service import ScreenCaptureService


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
    """
    Video source that consumes screen frames from the centralized ScreenCaptureService.
    This source reads frames from the service buffer and sends them to the video track.
    """

    def __init__(self, video_track, loop, fps=30):
        super().__init__(video_track, loop)
        self.fps = fps
        self.service = ScreenCaptureService()

    def run(self):
        """Consumes frames from the centralized service and sends them to the video track."""
        self.running = True
        logger.info("--- ScreenCaptureSource thread started ---")

        # Start the centralized service if not already running
        if not self.service.is_running():
            def error_callback(error_msg):
                logger.error(f"Screen capture service error: {error_msg}")

            self.service.start(fps=self.fps, error_callback=error_callback)

        frame_time = 1.0 / self.fps

        while self.running:
            try:
                # Get the latest frame from the centralized service
                frame = self.service.get_latest_frame()

                if frame is not None and frame.size > 0:
                    logger.debug(
                        "ScreenCaptureSource: Frame received from service."
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
                time.sleep(frame_time)

            except Exception as e:
                logger.error(f"Error in screen capture loop: {e}")
                time.sleep(0.5)  # Pause before retrying

        logger.info("--- ScreenCaptureSource thread finished ---")
        # Note: We don't stop the service here as other consumers may be using it
