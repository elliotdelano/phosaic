#!/usr/bin/env python3
"""
Centralized screen capture service for capturing and buffering screen frames.
Multiple consumers can request frames from this single service.
Supports both X11 and Wayland display servers.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Try to import mss for X11 support
try:
    from mss import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False
    logger.warning("mss not available, X11 capture will not work")

# Try to import pyscreenshot for Wayland support
try:
    import pyscreenshot as ImageGrab
    PYSCREENSHOT_AVAILABLE = True
except ImportError:
    PYSCREENSHOT_AVAILABLE = False
    logger.warning("pyscreenshot not available, Wayland capture may not work")


class ScreenCaptureService:
    """
    Centralized screen capture service that captures frames once
    and provides them to multiple consumers via a thread-safe buffer.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern to ensure only one instance exists."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the screen capture service."""
        if self._initialized:
            return

        self._initialized = True
        self._running = False
        self._thread = None
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._fps = 30
        self._sct = None
        self._monitor = None
        self._error_callback = None
        self._capture_method = None  # 'mss', 'pyscreenshot', 'grim', 'gnome-screenshot', or 'ffmpeg'
        self._screen_size = None  # (width, height)
        self._target_size = None  # Target resolution for downscaling (None = no scaling)
        self._ffmpeg_process = None  # FFmpeg subprocess for capture
        self._ffmpeg_pipe = None  # Pipe for reading frames from FFmpeg

    def start(self, fps=30, error_callback=None, max_resolution=None):
        """
        Start the screen capture service.

        Args:
            fps: Frames per second for capture (default: 30)
            error_callback: Optional callback function for errors (signature: func(error_message))
            max_resolution: Maximum resolution tuple (width, height) for downscaling (None = no scaling)
        """
        if self._running:
            logger.warning("Screen capture service is already running")
            return

        self._fps = fps
        self._error_callback = error_callback
        self._target_size = max_resolution
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("Screen capture service started")

    def stop(self):
        """Stop the screen capture service."""
        if not self._running:
            return

        self._running = False
        
        # Stop FFmpeg process if running
        if self._ffmpeg_process:
            try:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=2)
            except:
                try:
                    self._ffmpeg_process.kill()
                except:
                    pass
            self._ffmpeg_process = None
            self._ffmpeg_pipe = None
        
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        with self._frame_lock:
            self._latest_frame = None

        logger.info("Screen capture service stopped")

    def _resize_frame(self, frame):
        """
        Resize frame if target size is set and frame is larger.
        
        Args:
            frame: numpy array frame
            
        Returns:
            Resized frame or original if no resizing needed
        """
        if frame is None or self._target_size is None:
            return frame
            
        try:
            height, width = frame.shape[:2]
            target_width, target_height = self._target_size
            
            # Only downscale, never upscale
            if width > target_width or height > target_height:
                # Calculate scaling factor to fit within target while maintaining aspect ratio
                scale_w = target_width / width
                scale_h = target_height / height
                scale = min(scale_w, scale_h)
                
                new_width = int(width * scale)
                new_height = int(height * scale)
                
                frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
                logger.debug(f"Resized frame from {width}x{height} to {new_width}x{new_height}")
                
        except Exception as e:
            logger.debug(f"Frame resize error: {e}")
            
        return frame

    def _normalize_frame(self, frame):
        """
        Normalize frame to ensure it's in the correct format for video streaming.
        
        Args:
            frame: numpy array frame
            
        Returns:
            Normalized frame (BGR, uint8, contiguous) or None if invalid
        """
        if frame is None:
            return None
            
        try:
            # Ensure it's a numpy array
            if not isinstance(frame, np.ndarray):
                return None
                
            # Check frame has valid shape
            if len(frame.shape) != 3 or frame.shape[2] not in [3, 4]:
                logger.debug(f"Invalid frame shape: {frame.shape}")
                return None
                
            # Ensure uint8 dtype
            if frame.dtype != np.uint8:
                frame = frame.astype(np.uint8)
                
            # Convert BGRA to BGR if needed
            if frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            elif frame.shape[2] == 3:
                # Ensure it's BGR (pyscreenshot returns RGB, grim/gnome-screenshot return BGR)
                # Check if it's RGB by comparing with known patterns, but for safety
                # we'll assume it's already BGR if from cv2.imread or after conversion
                pass
            
            # Resize if needed (downscale for performance)
            frame = self._resize_frame(frame)
                
            # Ensure frame is contiguous in memory
            frame = np.ascontiguousarray(frame)
            
            # Validate frame dimensions
            height, width = frame.shape[:2]
            if height == 0 or width == 0:
                logger.debug(f"Invalid frame dimensions: {width}x{height}")
                return None
                
            return frame
        except Exception as e:
            logger.debug(f"Frame normalization error: {e}")
            return None

    def get_latest_frame(self):
        """
        Get the latest captured frame in a thread-safe manner.
        Frames are normalized to ensure consistent format (BGR, uint8, contiguous).

        Returns:
            numpy.ndarray: The latest frame (BGR format, uint8, contiguous), or None if no frame is available
        """
        with self._frame_lock:
            if self._latest_frame is not None:
                # Return a normalized copy to ensure thread safety and format consistency
                normalized = self._normalize_frame(self._latest_frame)
                return normalized.copy() if normalized is not None else None
            return None

    def is_running(self):
        """Check if the service is currently running."""
        return self._running

    def _detect_display_server(self):
        """Detect the display server type and available capture methods."""
        xdg_session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        wayland_display = os.environ.get("WAYLAND_DISPLAY")
        display = os.environ.get("DISPLAY")

        # Check if we're on Wayland
        is_wayland = xdg_session == "wayland" or wayland_display is not None

        # Determine available capture methods
        available_methods = []

        if is_wayland:
            logger.info("Wayland session detected")
            # Use FFmpeg only for Wayland (via PipeWire or x11grab with XWayland)
            if self._check_command("ffmpeg"):
                available_methods.append("ffmpeg")
            else:
                logger.warning(
                    "FFmpeg not found. Screen capture on Wayland requires FFmpeg. "
                    "Please install FFmpeg: sudo dnf install ffmpeg (Fedora) or "
                    "sudo apt install ffmpeg (Ubuntu/Debian)"
                )
        else:
            logger.info("X11 session detected")
            if MSS_AVAILABLE:
                available_methods.append("mss")

        return is_wayland, available_methods

    def _check_command(self, command):
        """Check if a command is available in PATH."""
        return shutil.which(command) is not None

    def _get_screen_size(self):
        """Get the screen size using available methods."""
        # Try xrandr first (works on both X11 and Wayland with XWayland)
        try:
            result = subprocess.run(
                ["xrandr"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if " connected " in line and "x" in line:
                        # Parse resolution from line like "DP-1 connected 1920x1080+0+0"
                        parts = line.split()
                        for part in parts:
                            if "x" in part and "+" not in part:
                                try:
                                    width, height = map(int, part.split("x"))
                                    return (width, height)
                                except ValueError:
                                    continue
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Fallback: try to get from environment or use defaults
        # On Wayland, we might need to use other methods
        return (1920, 1080)  # Default fallback

    def _capture_with_mss(self, monitor):
        """Capture screen using mss (X11)."""
        if not MSS_AVAILABLE:
            return None
        try:
            sct_img = self._sct.grab(monitor)
            if sct_img is None:
                return None
            frame = np.array(sct_img)
            if frame.size == 0:
                return None
            # Convert BGRA to BGR
            if len(frame.shape) == 3 and frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            return np.ascontiguousarray(frame)
        except Exception as e:
            logger.debug(f"mss capture error: {e}")
            return None

    def _capture_with_pyscreenshot(self):
        """Capture screen using pyscreenshot (Wayland)."""
        if not PYSCREENSHOT_AVAILABLE:
            return None
        try:
            # pyscreenshot automatically uses the right backend for Wayland
            img = ImageGrab.grab()
            # Convert PIL Image to numpy array (PIL returns RGB)
            frame = np.array(img)
            
            # Ensure frame is valid
            if frame.size == 0:
                return None
                
            # Convert RGB to BGR for OpenCV/video streaming compatibility
            # pyscreenshot returns RGB, but we need BGR for video track
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            elif len(frame.shape) == 3 and frame.shape[2] == 4:
                # RGBA to BGRA then to BGR
                frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGRA)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                
            return np.ascontiguousarray(frame)
        except Exception as e:
            logger.debug(f"pyscreenshot capture error: {e}")
            return None

    def _capture_with_grim(self):
        """Capture screen using grim (wlroots/Wayland) - optimized with stdout."""
        try:
            # Try to use grim with stdout first (faster, no file I/O)
            result = subprocess.run(
                ["grim", "-"],
                capture_output=True,
                timeout=2
            )

            if result.returncode == 0 and result.stdout:
                # Decode PNG from stdout directly
                nparr = np.frombuffer(result.stdout, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is not None:
                    return np.ascontiguousarray(frame)

            # Fallback to file-based method if stdout doesn't work
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                tmp_path = tmp_file.name

            result = subprocess.run(
                ["grim", tmp_path],
                capture_output=True,
                timeout=2
            )

            if result.returncode != 0:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return None

            # Read the image
            frame = cv2.imread(tmp_path)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

            if frame is None:
                return None

            return np.ascontiguousarray(frame)
        except Exception as e:
            logger.debug(f"grim capture error: {e}")
            return None

    def _capture_with_gnome_screenshot(self):
        """Capture screen using gnome-screenshot (GNOME Wayland)."""
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                tmp_path = tmp_file.name

            # Use gnome-screenshot to capture screen (non-interactive, file output)
            result = subprocess.run(
                ["gnome-screenshot", "-f", tmp_path],
                capture_output=True,
                timeout=3
            )

            if result.returncode != 0:
                os.unlink(tmp_path)
                return None

            # Read the image
            frame = cv2.imread(tmp_path)
            os.unlink(tmp_path)

            if frame is None:
                return None

            return np.ascontiguousarray(frame)
        except Exception as e:
            logger.debug(f"gnome-screenshot capture error: {e}")
            return None

    def _capture_with_ffmpeg(self):
        """
        Capture screen using FFmpeg directly on Wayland.
        Uses x11grab with XWayland (most reliable) or PipeWire as fallback.
        """
        try:
            width, height = self._screen_size
            display = os.environ.get("DISPLAY")
            
            # Try x11grab with XWayland first (most reliable on Wayland)
            # Most Wayland sessions have XWayland enabled for compatibility
            if display:
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-f", "x11grab",
                    "-s", f"{width}x{height}",
                    "-i", display,
                    "-vf", "format=bgr24",
                    "-frames:v", "1",
                    "-f", "rawvideo",
                    "-pix_fmt", "bgr24",
                    "-loglevel", "error",  # Suppress FFmpeg output
                    "-"
                ]
                
                try:
                    result = subprocess.run(
                        ffmpeg_cmd,
                        capture_output=True,
                        timeout=2,
                        check=False
                    )
                    
                    if result.returncode == 0 and result.stdout:
                        frame_size = width * height * 3
                        if len(result.stdout) >= frame_size:
                            raw_frame = result.stdout[:frame_size]
                            frame = np.frombuffer(raw_frame, dtype=np.uint8)
                            frame = frame.reshape((height, width, 3))
                            return np.ascontiguousarray(frame)
                except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                    logger.debug(f"FFmpeg x11grab failed: {e}")
            
            # Fallback: Try PipeWire (requires PipeWire screen sharing to be set up)
            # This is less reliable as it requires the screen to be shared first
            try:
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-f", "pipewire",
                    "-i", "screen-capture-stream",  # PipeWire screen capture source
                    "-vf", f"scale={width}:{height},format=bgr24",
                    "-frames:v", "1",
                    "-f", "rawvideo",
                    "-pix_fmt", "bgr24",
                    "-loglevel", "error",
                    "-"
                ]
                
                result = subprocess.run(
                    ffmpeg_cmd,
                    capture_output=True,
                    timeout=2,
                    check=False
                )
                
                if result.returncode == 0 and result.stdout:
                    frame_size = width * height * 3
                    if len(result.stdout) >= frame_size:
                        raw_frame = result.stdout[:frame_size]
                        frame = np.frombuffer(raw_frame, dtype=np.uint8)
                        frame = frame.reshape((height, width, 3))
                        return np.ascontiguousarray(frame)
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.debug(f"FFmpeg PipeWire failed: {e}")
            
            logger.debug("FFmpeg capture failed: x11grab and PipeWire both unavailable")
            return None
            
        except Exception as e:
            logger.debug(f"ffmpeg capture error: {e}")
            return None

    def _capture_frame(self):
        """Capture a frame using the selected method."""
        if self._capture_method == "mss":
            return self._capture_with_mss(self._monitor)
        elif self._capture_method == "ffmpeg":
            return self._capture_with_ffmpeg()
        else:
            return None

    def _capture_loop(self):
        """Main capture loop running in a separate thread."""
        # Detect display server and available capture methods
        is_wayland, available_methods = self._detect_display_server()

        if not available_methods:
            error_msg = (
                "No screen capture method available. "
                "For X11: install 'mss' (pip install mss). "
                "For Wayland: install 'ffmpeg' (sudo dnf install ffmpeg on Fedora, "
                "or sudo apt install ffmpeg on Ubuntu/Debian)."
            )
            logger.error(error_msg)
            if self._error_callback:
                self._error_callback(error_msg)
            self._running = False
            return

        # Select the best available capture method
        # Priority: mss (X11) > ffmpeg (Wayland)
        if "mss" in available_methods:
            self._capture_method = "mss"
        elif "ffmpeg" in available_methods:
            self._capture_method = "ffmpeg"
        else:
            self._capture_method = available_methods[0] if available_methods else None

        logger.info(f"Using capture method: {self._capture_method} at {self._fps} FPS")

        # Initialize capture method
        try:
            if self._capture_method == "mss":
                if not MSS_AVAILABLE:
                    raise RuntimeError("mss not available")
                self._sct = mss()
                # Validate monitors are available
                if not self._sct.monitors or len(self._sct.monitors) == 0:
                    raise RuntimeError("No monitors detected for screen capture.")
                # Use the primary monitor (index 1)
                if len(self._sct.monitors) > 1:
                    monitor = self._sct.monitors[1]
                else:
                    monitor = self._sct.monitors[0]
                if "width" not in monitor or "height" not in monitor:
                    raise RuntimeError("Invalid monitor configuration detected.")
                self._monitor = monitor
                self._screen_size = (monitor["width"], monitor["height"])
                logger.info(
                    f"Screen capture initialized: {monitor['width']}x{monitor['height']} "
                    f"(method: {self._capture_method})"
                )
            elif self._capture_method == "ffmpeg":
                # For FFmpeg on Wayland, get screen size
                self._screen_size = self._get_screen_size()
                logger.info(
                    f"Screen capture initialized: {self._screen_size[0]}x{self._screen_size[1]} "
                    f"(method: {self._capture_method}, Wayland)"
                )
            else:
                raise RuntimeError(f"Unknown capture method: {self._capture_method}")

            frame_time = 1.0 / self._fps
            consecutive_errors = 0
            max_consecutive_errors = 10  # More lenient for slower methods

            while self._running:
                try:
                    # Capture frame using selected method
                    frame = self._capture_frame()

                    if frame is None or frame.size == 0:
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            error_msg = (
                                f"Failed to capture screen after {max_consecutive_errors} attempts "
                                f"using {self._capture_method}."
                            )
                            logger.error(error_msg)
                            if self._error_callback:
                                self._error_callback(error_msg)
                            break
                        time.sleep(0.1)
                        continue

                    consecutive_errors = 0  # Reset error counter on success

                    # Normalize frame before storing
                    normalized_frame = self._normalize_frame(frame)
                    if normalized_frame is None:
                        logger.debug("Frame normalization failed, skipping frame")
                        time.sleep(0.1)
                        continue

                    # Update the latest frame in a thread-safe manner
                    with self._frame_lock:
                        self._latest_frame = normalized_frame

                    # Wait to maintain the desired FPS
                    time.sleep(frame_time)

                except Exception as e:
                    error_str = str(e)
                    logger.error(f"Screen capture error: {error_str}")

                    # Provide helpful error messages
                    if "XGetImage" in error_str or "X11" in error_str:
                        detailed_msg = (
                            f"X11 display error: {error_str}. "
                            "Trying alternative capture methods..."
                        )
                        logger.warning(detailed_msg)
                        # Try to switch to Wayland method if available
                        if is_wayland and "ffmpeg" in available_methods and self._capture_method == "mss":
                            logger.info("Switching to ffmpeg for Wayland compatibility")
                            self._capture_method = "ffmpeg"
                            if self._sct:
                                try:
                                    self._sct.close()
                                except:
                                    pass
                                self._sct = None
                            continue
                    else:
                        if self._error_callback:
                            self._error_callback(f"Screen capture error: {error_str}")

                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        break
                    # Wait a bit before retrying
                    time.sleep(0.1)

        except Exception as e:
            error_str = str(e)
            error_msg = f"Failed to initialize screen capture: {error_str}"
            logger.error(error_msg)
            if self._error_callback:
                self._error_callback(error_msg)

        # Cleanup
        if self._sct:
            try:
                self._sct.close()
            except:
                pass
            self._sct = None
        self._running = False

