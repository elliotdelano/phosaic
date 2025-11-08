#!/usr/bin/env python3
"""
ScreenCaptureThread for capturing and processing screen frames.
"""

import os
import time

import cv2
import numpy as np
from mss import mss
from PyQt5.QtCore import QThread, pyqtSignal, QWaitCondition, QMutex


class ScreenCaptureThread(QThread):
    """Thread for capturing and processing screen frames."""

    frame_ready = pyqtSignal(object)  # frame
    error_occurred = pyqtSignal(str)  # error message

    def __init__(self, fps=30):
        super().__init__()
        self.fps = fps
        self.running = False
        self.sct = None
        self.mutex = QMutex()
        self.condition = QWaitCondition()

    def run(self):
        """Main thread loop for screen capture."""
        self.running = True
        
        # Check display environment on Linux
        display = os.environ.get('DISPLAY')
        xdg_session = os.environ.get('XDG_SESSION_TYPE', '').lower()
        
        # On Linux, require DISPLAY to be set (indicates X11/XWayland is available)
        # Note: XWayland provides X11 compatibility even on Wayland sessions
        if not display and os.name != 'nt':
            error_msg = (
                "DISPLAY environment variable not set. "
                "Screen capture requires X11 display access. "
                "If running on Wayland, ensure XWayland is enabled or switch to X11 session."
            )
            print(f"ERROR: {error_msg}")
            self.error_occurred.emit(error_msg)
            return
        
        # Warn but don't fail if Wayland is detected but DISPLAY is set
        # This allows XWayland to work
        if xdg_session == 'wayland' and display:
            print(f"WARNING: Wayland session detected, but DISPLAY={display} is set. "
                  "Attempting to use X11/XWayland compatibility layer.")
        
        try:
            # Use context manager for proper resource management on Linux
            # This ensures X11 resources are properly cleaned up
            with mss() as sct:
                self.sct = sct  # Keep reference for external access if needed
                
                # Validate monitors are available
                if not sct.monitors or len(sct.monitors) == 0:
                    error_msg = "No monitors detected for screen capture."
                    print(f"ERROR: {error_msg}")
                    self.error_occurred.emit(error_msg)
                    return
                
                # Use the primary monitor (index 1)
                # monitors[0] is all monitors combined, monitors[1] is the primary monitor
                if len(sct.monitors) > 1:
                    monitor = sct.monitors[1]
                else:
                    monitor = sct.monitors[0]
                
                # Validate monitor dimensions
                if 'width' not in monitor or 'height' not in monitor:
                    error_msg = "Invalid monitor configuration detected."
                    print(f"ERROR: {error_msg}")
                    self.error_occurred.emit(error_msg)
                    return
                
                print(f"Screen capture initialized: {monitor['width']}x{monitor['height']} "
                      f"(DISPLAY={display})")

                frame_time = 1.0 / self.fps
                sleep_ms = int(frame_time * 1000)
                consecutive_errors = 0
                max_consecutive_errors = 5

                while self.running:
                    try:
                        # Grab the data
                        sct_img = sct.grab(monitor)
                        
                        if sct_img is None:
                            consecutive_errors += 1
                            if consecutive_errors >= max_consecutive_errors:
                                error_msg = "Failed to grab screen image after multiple attempts."
                                print(f"ERROR: {error_msg}")
                                self.error_occurred.emit(error_msg)
                                break
                            continue
                        
                        consecutive_errors = 0  # Reset error counter on success

                        # Convert to a numpy array - mss returns BGRA format
                        frame = np.array(sct_img)
                        
                        if frame.size == 0:
                            continue

                        # Convert BGRA to BGR for OpenCV compatibility
                        if len(frame.shape) == 3 and frame.shape[2] == 4:  # BGRA format
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                        # Ensure frame is contiguous in memory for QImage
                        frame = np.ascontiguousarray(frame)

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
                        print(f"Screen capture error: {error_str}")
                        
                        # Provide helpful error messages for common issues
                        if "XGetImage" in error_str or "X11" in error_str:
                            detailed_msg = (
                                f"X11 display error: {error_str}. "
                                "This usually means:\n"
                                "1. Running on Wayland instead of X11 (switch to X11 session)\n"
                                "2. DISPLAY environment variable not set correctly\n"
                                "3. X11 permissions issue (check xhost/xauth)"
                            )
                            self.error_occurred.emit(detailed_msg)
                        else:
                            self.error_occurred.emit(f"Screen capture error: {error_str}")
                        
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            break
                        # Wait a bit before retrying
                        time.sleep(0.1)
        
        except Exception as e:
            error_str = str(e)
            error_msg = f"Failed to initialize screen capture: {error_str}"
            print(f"ERROR: {error_msg}")
            self.error_occurred.emit(error_msg)
        
        # Context manager automatically closes mss instance
        self.sct = None

    def stop(self):
        """Stop the screen capture thread."""
        self.running = False
        # Wake up the thread if it's waiting
        self.mutex.lock()
        self.condition.wakeAll()
        self.mutex.unlock()
        self.wait()
