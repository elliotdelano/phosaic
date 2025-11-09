import argparse
import asyncio
import json
import logging
import queue
import threading
import time
from concurrent.futures import TimeoutError

import av
import cv2
import numpy as np
from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import VideoStreamTrack
from video_source import ScreenCaptureSource, VideoFileSource
from websockets.client import connect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



class RTCVideoStreamTrack(VideoStreamTrack):
    """
    A video track that receives frames from an external source, performs a
    perspective warp if specified, and queues them for sending.
    """

    kind = "video"

    def __init__(self, warp_matrix=None, output_size=(640, 480)):
        super().__init__()
        self.queue = asyncio.Queue(maxsize=1)
        self.warp_matrix = warp_matrix
        self.output_size = output_size if output_size is not None else (640, 480)

    async def recv(self):
        """Receives the next frame from the queue and returns it as a VideoFrame."""
        frame = await self.queue.get()

        try:
            pts, time_base = await self.next_timestamp()
            video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
            video_frame.pts = pts
            video_frame.time_base = time_base
            return video_frame
        except Exception as e:
            logger.error(f"RTCVideoStreamTrack: Error creating VideoFrame: {e}")
            return None

    def add_frame(self, frame):
        """
        Adds a frame to the queue, warping it first if a warp_matrix is set.
        Discards an old frame if the queue is full.
        """
        try:
            if frame is None:
                return

            # Warp the frame if a matrix is defined
            if self.warp_matrix is not None and self.output_size is not None:
                warped_frame = cv2.warpPerspective(
                    frame, self.warp_matrix, self.output_size
                )
                processed_frame = warped_frame
            else:
                # If no warp is specified, use the frame as is
                processed_frame = frame

            if not hasattr(processed_frame, "shape") or len(processed_frame.shape) != 3:
                logger.warning("Invalid frame after processing, skipping.")
                return

            if self.queue.full():
                self.queue.get_nowait()

            self.queue.put_nowait(processed_frame)
        except Exception as e:
            logger.error(f"RTCVideoStreamTrack: Error adding frame to queue: {e}")


class Coordinator:
    """WebRTC Coordinator for establishing multiple peer connections."""

    def __init__(self):
        self.status_queue = queue.Queue()
        self.loop = None
        self.webrtc_thread = None
        self.video_source = None
        self.connections = {}  # subordinate_id -> { 'pc': RTCPeerConnection, 'video_track': RTCVideoStreamTrack, 'status': str }
        self.coordinator_id = None
        self.websocket = None
        self._video_source_started = False
        self.subordinate_display_sizes = {}  # subordinate_id -> (width, height)
        self._video_source_type = "screen"  # "screen" or "file"
        self._video_file_path = None

    def start(self):
        """Start the coordinator's main event loop and websocket connection."""
        if self.webrtc_thread is not None and self.webrtc_thread.is_alive():
            logger.warning("Coordinator already started.")
            return

        self.webrtc_thread = threading.Thread(target=self._run_main_loop)
        self.webrtc_thread.daemon = True
        self.webrtc_thread.start()

    def _run_main_loop(self):
        """Runs the asyncio event loop."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._connect_and_listen())
        except Exception as e:
            logger.error(f"Main loop encountered an error: {e}")
            self.status_queue.put(("error", f"Main loop failed: {e}"))
        finally:
            self.loop.run_until_complete(self.shutdown())
            self.loop.close()

    async def _connect_and_listen(self):
        """Connects to the signaling server and listens for messages."""
        uri = "ws://localhost:3000"
        try:
            async with connect(uri) as websocket:
                self.websocket = websocket
                await self._register_with_server()
                async for message in websocket:
                    await self._handle_signaling_message(message)
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.status_queue.put(("error", f"WebSocket connection failed: {e}"))

    async def _register_with_server(self):
        """Registers as a coordinator with the signaling server."""
        await self.websocket.send(json.dumps({"type": "register-coordinator"}))
        message = await self.websocket.recv()
        data = json.loads(message)
        if data.get("type") == "registered":
            self.coordinator_id = data["id"]
            self.status_queue.put(
                ("registered", f"Registered with ID: {self.coordinator_id}")
            )
            logger.info(
                f"Registered with server. Coordinator ID: {self.coordinator_id}"
            )
        else:
            raise Exception(f"Failed to register with server. Response: {data}")

    def connect_by_id(self, subordinate_id, warp_matrix=None, output_size=None, screen_points=None, source_screen_size=None):
        """Connect to a subordinate using the given ID and optional warp parameters."""
        if not self.loop or not self.loop.is_running():
            self.status_queue.put(
                ("error", "Coordinator not started. Call start() first.")
            )
            logger.error("Cannot connect, event loop is not running.")
            return

        if subordinate_id in self.connections:
            self.status_queue.put(
                ("warning", f"Already connected or connecting to {subordinate_id}")
            )
            return

        # If output_size is not provided, try to get it from stored display sizes
        # or request it from the server
        if output_size is None:
            if subordinate_id in self.subordinate_display_sizes:
                output_size = self.subordinate_display_sizes[subordinate_id]
                logger.info(f"Using stored display size for {subordinate_id}: {output_size}")
            else:
                # Request display size from server before connecting
                self.status_queue.put(
                    ("info", f"Requesting display size for {subordinate_id}...")
                )
                asyncio.run_coroutine_threadsafe(
                    self._request_subordinate_info_and_connect(subordinate_id, warp_matrix, screen_points, source_screen_size),
                    self.loop,
                )
                return

        self.status_queue.put(
            ("connecting", f"Connecting to subordinate {subordinate_id}...")
        )
        asyncio.run_coroutine_threadsafe(
            self._create_peer_connection(subordinate_id, warp_matrix, output_size, screen_points, source_screen_size),
            self.loop,
        )

    async def _create_peer_connection(
        self, subordinate_id, warp_matrix=None, output_size=None, screen_points=None, source_screen_size=None
    ):
        """Creates and sets up a new RTCPeerConnection."""
        if subordinate_id in self.connections:
            logger.warning(
                f"Connection attempt for existing subordinate {subordinate_id}"
            )
            return

        # Set default output size if not provided
        if output_size is None:
            output_size = (640, 480)
        logger.info(f"[Coordinator] Creating peer connection for {subordinate_id} with output_size={output_size}")

        pc = RTCPeerConnection()
        video_track = RTCVideoStreamTrack(
            warp_matrix=warp_matrix, output_size=output_size
        )
        pc.addTrack(video_track)

        # Store screen_points as a list for serialization (convert numpy array to list if needed)
        screen_points_list = None
        if screen_points is not None:
            if hasattr(screen_points, 'tolist'):
                screen_points_list = screen_points.tolist()
            else:
                screen_points_list = screen_points

        self.connections[subordinate_id] = {
            "pc": pc,
            "video_track": video_track,
            "status": "connecting",
            "warp_matrix": warp_matrix,
            "output_size": output_size,
            "screen_points": screen_points_list,  # Store for later recalculation
        }

        await self._setup_pc_handlers_and_offer(pc, subordinate_id)

    async def _setup_pc_handlers_and_offer(self, pc, subordinate_id):
        """Sets up event handlers for a peer connection and creates an offer."""

        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logger.info(
                f"ICE connection state for {subordinate_id} is {pc.iceConnectionState}"
            )
            if pc.iceConnectionState == "failed":
                self.status_queue.put(
                    ("failed", f"ICE connection failed for {subordinate_id}")
                )
                await self.cleanup_connection(subordinate_id)
            elif pc.iceConnectionState in ["connected", "completed"]:
                self.connections[subordinate_id]["status"] = "connected"
                self.status_queue.put(
                    ("connected", f"Connected to subordinate {subordinate_id}")
                )
                self._start_video_source_if_needed()
                if self.video_source:
                    self.video_source.add_track(
                        self.connections[subordinate_id]["video_track"]
                    )
            elif pc.iceConnectionState == "disconnected":
                self.status_queue.put(
                    ("disconnected", f"Connection lost with {subordinate_id}")
                )
                await self.cleanup_connection(subordinate_id)

        # Data channel setup
        channel = pc.createDataChannel("chat")

        @channel.on("open")
        def on_open():
            logger.info(f"Data channel for {subordinate_id} is open")
            channel.send(f"Hello from Python coordinator to {subordinate_id}!")
            self.status_queue.put(
                ("channel_open", f"Data channel for {subordinate_id} opened")
            )

        @channel.on("message")
        def on_message(message):
            logger.info(f"Received message from {subordinate_id}: {message}")
            try:
                msg_obj = json.loads(message)
                if isinstance(msg_obj, dict) and msg_obj.get("type") == "subordinate-info":
                    # This is a fallback - display size should already be received from server
                    # during initial connection, but handle it here just in case
                    width = msg_obj.get("width")
                    height = msg_obj.get("height")
                    if width and height:
                        logger.info(f"[Coordinator] Received subordinate-info via data channel from {subordinate_id}: width={width}, height={height}")
                        # Only update if we don't already have this info
                        if subordinate_id not in self.subordinate_display_sizes:
                            self.subordinate_display_sizes[subordinate_id] = (width, height)
                            # Update the connection with the actual display size if needed
                            asyncio.ensure_future(self._update_connection_output_size(subordinate_id, (width, height)))
                            self.status_queue.put(("subordinate-info", f"Received display size from {subordinate_id}: {width}x{height}"))
                else:
                    self.status_queue.put(("message", f"Msg from {subordinate_id}: {message}"))
            except Exception as e:
                logger.warning(f"Failed to parse data channel message from {subordinate_id}: {e}")
                self.status_queue.put(("message", f"Msg from {subordinate_id}: {message}"))

        # Create and send offer
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        message = {
            "type": "offer",
            "sourceId": self.coordinator_id,
            "targetId": subordinate_id,
            "offer": {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
        }
        logger.info(f"[Coordinator] Sending offer to {subordinate_id} with output_size={self.connections[subordinate_id]['output_size']}")
        await self.websocket.send(json.dumps(message))
        self.status_queue.put(("offer_sent", f"WebRTC offer sent to {subordinate_id}"))

    def set_video_source_type(self, source_type, video_file_path=None):
        """
        Set the video source type.
        
        Args:
            source_type: "screen" or "file"
            video_file_path: Path to video file (required if source_type is "file")
        """
        if source_type not in ["screen", "file"]:
            logger.error(f"Invalid video source type: {source_type}")
            return False
        
        # If switching source type, stop current source
        if self._video_source_started and self.video_source:
            logger.info(f"Stopping current video source to switch to {source_type}")
            self.video_source.stop()
            self.video_source = None
            self._video_source_started = False
        
        self._video_source_type = source_type
        if source_type == "file":
            if not video_file_path:
                logger.error("Video file path required for file source type")
                return False
            self._video_file_path = video_file_path
        else:
            self._video_file_path = None
        
        # If there are active connections, start the new source
        if self.connections:
            self._start_video_source_if_needed()
            # Re-add all tracks to the new source
            for connection in self.connections.values():
                if self.video_source and connection.get("video_track"):
                    self.video_source.add_track(connection["video_track"])
        
        return True

    def _start_video_source_if_needed(self):
        """Starts the shared video source if it's not already running."""
        if not self._video_source_started:
            if self._video_source_type == "screen":
                logger.info("--- Starting shared ScreenCaptureSource ---")
                self.video_source = ScreenCaptureSource(self.loop)
            elif self._video_source_type == "file":
                if not self._video_file_path:
                    logger.error("Video file path not set for file source")
                    return
                logger.info(f"--- Starting shared VideoFileSource for {self._video_file_path} ---")
                self.video_source = VideoFileSource(self._video_file_path, self.loop)
            else:
                logger.error(f"Unknown video source type: {self._video_source_type}")
                return
            
            self.video_source.start()
            self._video_source_started = True
            logger.info(f"--- Shared {self._video_source_type} video source started ---")

    async def _request_subordinate_info_and_connect(self, subordinate_id, warp_matrix, screen_points, source_screen_size):
        """Request subordinate info from server and then connect."""
        # Request subordinate info
        request_message = {
            "type": "get-subordinate-info",
            "subordinateId": subordinate_id,
        }
        await self.websocket.send(json.dumps(request_message))
        logger.info(f"Requested subordinate info for {subordinate_id}")
        
        # Wait for the response (it will be handled in _handle_signaling_message)
        # Store pending connection info so we can use it when info arrives
        if not hasattr(self, "_pending_connections"):
            self._pending_connections = {}
        self._pending_connections[subordinate_id] = {
            "warp_matrix": warp_matrix,
            "screen_points": screen_points,
            "source_screen_size": source_screen_size,
        }

    async def _handle_signaling_message(self, message):
        """Handles incoming messages from the signaling server."""
        data = json.loads(message)
        msg_type = data.get("type")
        source_id = data.get("sourceId")

        logger.info(
            f"Received signaling message of type '{msg_type}' from '{source_id}'"
        )

        if msg_type == "registered":
            # If subordinate registration, store display size if present
            if "width" in data and "height" in data and "id" in data:
                logger.info(f"[Coordinator] Subordinate {data['id']} reported display size: width={data['width']}, height={data['height']}")
                self.subordinate_display_sizes[data["id"]] = (data["width"], data["height"])
            return

        if msg_type == "subordinate-info":
            # Response to get-subordinate-info request
            subordinate_id = data.get("subordinateId")
            if "error" in data:
                logger.warning(f"Failed to get subordinate info for {subordinate_id}: {data['error']}")
                self.status_queue.put(
                    ("error", f"Failed to get display size for {subordinate_id}: {data['error']}")
                )
                # Use default size if info not available
                output_size = (640, 480)
            else:
                width = data.get("width")
                height = data.get("height")
                if width and height:
                    output_size = (width, height)
                    self.subordinate_display_sizes[subordinate_id] = output_size
                    logger.info(f"[Coordinator] Received subordinate info for {subordinate_id}: {width}x{height}")
                    self.status_queue.put(
                        ("info", f"Received display size for {subordinate_id}: {width}x{height}")
                    )
                else:
                    logger.warning(f"Invalid subordinate info response: {data}")
                    output_size = (640, 480)
            
            # Check if there's a pending connection for this subordinate
            if hasattr(self, "_pending_connections") and subordinate_id in self._pending_connections:
                pending = self._pending_connections.pop(subordinate_id)
                
                # Recalculate warp matrix with the correct output size
                warp_matrix = pending.get("warp_matrix")
                screen_points = pending.get("screen_points")
                source_screen_size = pending.get("source_screen_size")
                
                if screen_points is not None and source_screen_size is not None:
                    # Convert screen_points back to numpy array if it's a list
                    if isinstance(screen_points, list):
                        screen_points_np = np.array(screen_points, dtype=np.float32)
                    else:
                        screen_points_np = screen_points
                    
                    # Ensure screen_points is in the right shape (4, 2)
                    if len(screen_points_np.shape) == 3:
                        screen_points_np = np.squeeze(screen_points_np, axis=1)
                    
                    if screen_points_np.shape[0] == 4:
                        # Map the ENTIRE source screen to the subordinate display, maintaining aspect ratio
                        src_width, src_height = source_screen_size
                        src_aspect = src_width / src_height if src_height > 0 else 1.0
                        
                        dst_width, dst_height = output_size
                        dst_aspect = dst_width / dst_height if dst_height > 0 else 1.0
                        
                        # Calculate how to fit the source screen within the destination while maintaining aspect ratio
                        if src_aspect > dst_aspect:
                            # Source is wider - fit to width, add letterboxing
                            fit_width = dst_width
                            fit_height = int(dst_width / src_aspect)
                            offset_x = 0
                            offset_y = (dst_height - fit_height) // 2
                        else:
                            # Source is taller - fit to height, add pillarboxing
                            fit_width = int(dst_height * src_aspect)
                            fit_height = dst_height
                            offset_x = (dst_width - fit_width) // 2
                            offset_y = 0
                        
                        # Create source rectangle (full screen corners)
                        src_rect = np.float32([
                            [0, 0],
                            [src_width, 0],
                            [src_width, src_height],
                            [0, src_height]
                        ])
                        
                        # Create destination rectangle that maintains aspect ratio
                        dst_rect = np.float32([
                            [offset_x, offset_y],
                            [offset_x + fit_width, offset_y],
                            [offset_x + fit_width, offset_y + fit_height],
                            [offset_x, offset_y + fit_height]
                        ])
                        
                        # Calculate homography from QR code corners to screen corners
                        # First, find the transformation from QR code corners to screen corners
                        qr_to_screen = cv2.getPerspectiveTransform(screen_points_np, src_rect)
                        
                        # Then, find transformation from screen corners to destination
                        screen_to_dst = cv2.getPerspectiveTransform(src_rect, dst_rect)
                        
                        # Combine transformations: QR -> Screen -> Destination
                        warp_matrix = screen_to_dst @ qr_to_screen
                        
                        logger.info(f"Recalculated warp matrix for {subordinate_id}: source screen {src_width}x{src_height} -> destination {fit_width}x{fit_height} (full display {dst_width}x{dst_height})")
                
                self.status_queue.put(
                    ("connecting", f"Connecting to subordinate {subordinate_id}...")
                )
                await self._create_peer_connection(
                    subordinate_id,
                    warp_matrix,
                    output_size,
                    screen_points,
                    source_screen_size
                )
            return

        connection = self.connections.get(source_id)
        if not connection:
            logger.warning(f"Received message for unknown subordinate: {source_id}")
            return

        pc = connection["pc"]

        if msg_type == "answer":
            answer = RTCSessionDescription(
                sdp=data["answer"]["sdp"], type=data["answer"]["type"]
            )
            await pc.setRemoteDescription(answer)
            self.status_queue.put(
                ("answer_received", f"WebRTC answer from {source_id}")
            )
        elif msg_type == "ice-candidate":
            candidate_info = data.get("candidate")
            if candidate_info and candidate_info.get("candidate"):
                try:
                    candidate = RTCIceCandidate(
                        candidate_info.get("candidate"),
                        sdpMid=candidate_info.get("sdpMid"),
                        sdpMLineIndex=candidate_info.get("sdpMLineIndex"),
                    )
                    await pc.addIceCandidate(candidate)
                except Exception as e:
                    logger.error(f"Error adding ICE candidate from {source_id}: {e}")
            else:
                logger.warning(f"Received empty ICE candidate from {source_id}")

    async def _update_connection_output_size(self, subordinate_id, new_output_size):
        """Update the connection's output size and recalculate warp matrix if screen_points are available."""
        connection = self.connections.get(subordinate_id)
        if not connection:
            logger.warning(f"Cannot update output size for unknown subordinate: {subordinate_id}")
            return

        screen_points = connection.get("screen_points")
        if screen_points is None:
            logger.info(f"No screen_points stored for {subordinate_id}, cannot recalculate warp matrix")
            return

        # Convert screen_points back to numpy array if it's a list
        if isinstance(screen_points, list):
            screen_points_np = np.array(screen_points, dtype=np.float32)
        else:
            screen_points_np = screen_points

        # Ensure screen_points is in the right shape (4, 2)
        if len(screen_points_np.shape) == 3:
            screen_points_np = np.squeeze(screen_points_np, axis=1)

        if screen_points_np.shape[0] != 4:
            logger.warning(f"Invalid screen_points shape for {subordinate_id}: {screen_points_np.shape}")
            return

        # Create new destination rectangle with the actual display size
        width, height = new_output_size
        dst_rect = np.float32([
            [0, 0],
            [width, 0],
            [width, height],
            [0, height]
        ])

        # Recalculate the perspective transform matrix
        new_warp_matrix = cv2.getPerspectiveTransform(screen_points_np, dst_rect)

        # Update the connection dictionary
        connection["warp_matrix"] = new_warp_matrix
        connection["output_size"] = new_output_size

        # Update the video track
        video_track = connection.get("video_track")
        if video_track:
            video_track.warp_matrix = new_warp_matrix
            video_track.output_size = new_output_size
            logger.info(f"Updated connection for {subordinate_id} with output_size={new_output_size}")
            self.status_queue.put(("warp_updated", f"Updated warp matrix for {subordinate_id} with display size {width}x{height}"))
        else:
            logger.warning(f"No video track found for {subordinate_id}")

    async def cleanup_connection(self, subordinate_id):
        """Cleans up a connection for a given subordinate."""
        connection = self.connections.pop(subordinate_id, None)
        if connection:
            logger.info(f"Cleaning up connection for {subordinate_id}")
            if self.video_source and connection.get("video_track"):
                self.video_source.remove_track(connection["video_track"])

            pc = connection["pc"]
            if pc.connectionState != "closed":
                await pc.close()

            if not self.connections and self.video_source:
                logger.info("--- No active connections, stopping video source ---")
                self.video_source.stop()
                self.video_source = None
                self._video_source_started = False

    async def shutdown(self):
        """Shuts down all connections and the video source."""
        logger.info("Shutting down coordinator...")
        subordinate_ids = list(self.connections.keys())
        for sub_id in subordinate_ids:
            await self.cleanup_connection(sub_id)

        if self.video_source:
            self.video_source.stop()
            self.video_source = None

        if self.websocket:
            await self.websocket.close()

        logger.info("Shutdown complete.")

    def get_status(self):
        """Get the latest status update if available."""
        try:
            return self.status_queue.get_nowait()
        except queue.Empty:
            return None


def main():
    parser = argparse.ArgumentParser(description="Python WebRTC coordinator")
    parser.add_argument(
        "ids", nargs="+", help="The ID(s) of the subordinate(s) to connect to"
    )
    args = parser.parse_args()

    coordinator = Coordinator()
    coordinator.start()

    # Wait for registration to complete
    print("Waiting for coordinator to register with the server...")
    registered = False
    while not registered:
        status = coordinator.get_status()
        if status:
            print(f"Status: {status[0]} - {status[1]}")
            if status[0] == "registered":
                registered = True
        time.sleep(0.1)

    # Connect to all specified subordinates
    for sub_id in args.ids:
        coordinator.connect_by_id(sub_id)

    # Keep the program running to monitor status
    try:
        while True:
            status = coordinator.get_status()
            if status:
                print(f"Status: {status[0]} - {status[1]}")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        if coordinator.loop and coordinator.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                coordinator.shutdown(), coordinator.loop
            )
            try:
                future.result(timeout=5)  # Wait for shutdown to complete
            except TimeoutError:
                print("Shutdown timed out.")
        if coordinator.webrtc_thread:
            coordinator.webrtc_thread.join(timeout=5)
        print("Shutdown complete.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
