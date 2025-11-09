import logging
import threading
import time

import cv2
import numpy as np

# Setup logger for this module
logger = logging.getLogger(__name__)

# Import the centralized screen capture service
# Use relative import if in same package, or absolute if needed
try:
    from components.screen_capture_service import ScreenCaptureService
except ImportError:
    # Fallback for different import paths
    import os
    import sys

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
    This source reads frames from the service buffer and sends them to multiple video tracks.
    """

    def __init__(self, loop, fps=30):
        super().__init__(None, loop)  # No specific track upfront
        self.fps = fps
        self.service = ScreenCaptureService()
        self.tracks = []
        self.lock = threading.Lock()

    def add_track(self, track):
        """Adds a video track to the list of tracks to receive frames."""
        with self.lock:
            if track not in self.tracks:
                self.tracks.append(track)
                logger.info(f"Track added. Total tracks: {len(self.tracks)}")

    def remove_track(self, track):
        """Removes a video track from the list."""
        with self.lock:
            if track in self.tracks:
                self.tracks.remove(track)
                logger.info(f"Track removed. Total tracks: {len(self.tracks)}")

    def run(self):
        """Consumes frames from the centralized service and sends them to the video tracks."""
        self.running = True
        logger.info("--- ScreenCaptureSource thread started ---")

        # Start the centralized service if not already running
        if not self.service.is_running():

            def error_callback(error_msg):
                logger.error(f"Screen capture service error: {error_msg}")

            # Set max resolution to 1920x1080 for better performance on Wayland
            # This reduces processing overhead while maintaining good quality
            max_resolution = (1920, 1080)
            self.service.start(
                fps=self.fps,
                error_callback=error_callback,
                max_resolution=max_resolution,
            )

        frame_time = 1.0 / self.fps

        while self.running:
            try:
                # Get the latest frame from the centralized service
                frame = self.service.get_latest_frame()

                if frame is not None and frame.size > 0:
                    # Validate frame format before sending to video track
                    if not isinstance(frame, np.ndarray):
                        logger.warning("Frame is not a numpy array, skipping")
                        time.sleep(frame_time)
                        continue

                    if len(frame.shape) != 3 or frame.shape[2] != 3:
                        logger.warning(
                            f"Invalid frame shape: {frame.shape}, expected (H, W, 3), skipping"
                        )
                        time.sleep(frame_time)
                        continue

                    if frame.dtype != np.uint8:
                        logger.warning(
                            f"Invalid frame dtype: {frame.dtype}, expected uint8, skipping"
                        )
                        time.sleep(frame_time)
                        continue

                    logger.debug(
                        f"ScreenCaptureSource: Frame received from service. "
                        f"Shape: {frame.shape}, dtype: {frame.dtype}"
                    )

                    # Ensure frame is contiguous before sending
                    if not frame.flags["C_CONTIGUOUS"]:
                        frame = np.ascontiguousarray(frame)

                    with self.lock:
                        for track in self.tracks:
                            if self.loop and self.loop.is_running():
                                self.loop.call_soon_threadsafe(track.add_frame, frame)
                            else:
                                logger.warning(
                                    "Loop not available, skipping frame for a track"
                                )

                # Maintain FPS
                time.sleep(frame_time)

            except Exception as e:
                logger.error(f"Error in screen capture loop: {e}")
                time.sleep(0.5)  # Pause before retrying

        logger.info("--- ScreenCaptureSource thread finished ---")
        # Note: We don't stop the service here as other consumers may be using it


class VideoFileSource(VideoSource):
    """
    Video source that reads frames from a video file.
    Supports looping playback and multiple video tracks.
    """

    def __init__(self, video_file_path, loop, fps=None, loop_video=True):
        """
        Initialize the video file source.
        
        Args:
            video_file_path: Path to the video file
            loop: asyncio event loop for thread-safe operations
            fps: Target FPS for playback (None = use video file's FPS)
            loop_video: Whether to loop the video when it ends
        """
        super().__init__(None, loop)  # No specific track upfront
        self.video_file_path = video_file_path
        self.fps = fps
        self.loop_video = loop_video
        self.tracks = []
        self.lock = threading.Lock()
        self.cap = None
        self.video_fps = None
        self.frame_width = None
        self.frame_height = None

    def add_track(self, track):
        """Adds a video track to the list of tracks to receive frames."""
        with self.lock:
            if track not in self.tracks:
                self.tracks.append(track)
                logger.info(f"Track added. Total tracks: {len(self.tracks)}")

    def remove_track(self, track):
        """Removes a video track from the list."""
        with self.lock:
            if track in self.tracks:
                self.tracks.remove(track)
                logger.info(f"Track removed. Total tracks: {len(self.tracks)}")

    def run(self):
        """Reads frames from the video file and sends them to the video tracks."""
        self.running = True
        logger.info(f"--- VideoFileSource thread started for {self.video_file_path} ---")

        try:
            # Open video file
            self.cap = cv2.VideoCapture(self.video_file_path)
            if not self.cap.isOpened():
                error_msg = f"Failed to open video file: {self.video_file_path}"
                logger.error(error_msg)
                self.running = False
                return

            # Get video properties
            self.video_fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            # Use video FPS if not specified
            if self.fps is None:
                self.fps = self.video_fps if self.video_fps > 0 else 30
            
            logger.info(
                f"Video file opened: {self.frame_width}x{self.frame_height} @ {self.video_fps} FPS, "
                f"playing at {self.fps} FPS"
            )

            frame_time = 1.0 / self.fps

            while self.running:
                ret, frame = self.cap.read()

                if not ret:
                    # End of video
                    if self.loop_video:
                        logger.debug("End of video reached, looping...")
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        logger.info("End of video reached, stopping playback")
                        break

                if frame is None or frame.size == 0:
                    logger.warning("Empty frame read from video file")
                    time.sleep(frame_time)
                    continue

                # Validate frame format
                if not isinstance(frame, np.ndarray):
                    logger.warning("Frame is not a numpy array, skipping")
                    time.sleep(frame_time)
                    continue

                if len(frame.shape) != 3 or frame.shape[2] != 3:
                    logger.warning(
                        f"Invalid frame shape: {frame.shape}, expected (H, W, 3), skipping"
                    )
                    time.sleep(frame_time)
                    continue

                if frame.dtype != np.uint8:
                    logger.warning(
                        f"Invalid frame dtype: {frame.dtype}, expected uint8, skipping"
                    )
                    time.sleep(frame_time)
                    continue

                # Ensure frame is contiguous before sending
                if not frame.flags["C_CONTIGUOUS"]:
                    frame = np.ascontiguousarray(frame)

                logger.debug(
                    f"VideoFileSource: Frame read from file. "
                    f"Shape: {frame.shape}, dtype: {frame.dtype}"
                )

                # Send frame to all tracks
                with self.lock:
                    for track in self.tracks:
                        if self.loop and self.loop.is_running():
                            self.loop.call_soon_threadsafe(track.add_frame, frame)
                        else:
                            logger.warning(
                                "Loop not available, skipping frame for a track"
                            )

                # Maintain FPS
                time.sleep(frame_time)

        except Exception as e:
            logger.error(f"Error in video file playback loop: {e}")
        finally:
            if self.cap:
                self.cap.release()
                self.cap = None
            logger.info("--- VideoFileSource thread finished ---")

    def stop(self):
        """Stops the video source loop."""
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None
