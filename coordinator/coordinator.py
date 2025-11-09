import argparse
import asyncio
import json
import logging
import queue
import threading
import time
from concurrent.futures import TimeoutError

import av
from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import VideoStreamTrack
from video_source import ScreenCaptureSource, VideoFileSource
from websockets.client import connect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RTCVideoStreamTrack(VideoStreamTrack):
    """
    A video track that receives frames from an external source like a queue.
    """

    kind = "video"

    def __init__(self):
        super().__init__()
        self.queue = asyncio.Queue(maxsize=1)

    async def recv(self):
        """Receives the next frame from the queue and returns it as a VideoFrame."""
        logger.debug("RTCVideoStreamTrack: Waiting for frame from queue...")
        frame = await self.queue.get()
        logger.debug(
            f"RTCVideoStreamTrack: Frame received from queue. "
            f"Shape: {frame.shape if hasattr(frame, 'shape') else 'unknown'}, "
            f"dtype: {frame.dtype if hasattr(frame, 'dtype') else 'unknown'}"
        )

        try:
            pts, time_base = await self.next_timestamp()
            video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
            video_frame.pts = pts
            video_frame.time_base = time_base
            logger.debug("RTCVideoStreamTrack: Returning VideoFrame with pts=%s", pts)
            return video_frame
        except Exception as e:
            logger.error(
                f"RTCVideoStreamTrack: Error creating VideoFrame: {e}. "
                f"Frame shape: {frame.shape if hasattr(frame, 'shape') else 'unknown'}, "
                f"dtype: {frame.dtype if hasattr(frame, 'dtype') else 'unknown'}"
            )
            # Return a black frame as fallback
            import numpy as np

            fallback_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            pts, time_base = await self.next_timestamp()
            video_frame = av.VideoFrame.from_ndarray(fallback_frame, format="bgr24")
            video_frame.pts = pts
            video_frame.time_base = time_base
            return video_frame

    def add_frame(self, frame):
        """Adds a frame to the queue, discarding an old one if full."""
        try:
            # Validate frame before adding to queue
            if frame is None:
                logger.warning(
                    "RTCVideoStreamTrack: Attempted to add None frame, skipping"
                )
                return

            if not hasattr(frame, "shape") or not hasattr(frame, "dtype"):
                logger.warning(
                    f"RTCVideoStreamTrack: Invalid frame type: {type(frame)}, skipping"
                )
                return

            if len(frame.shape) != 3 or frame.shape[2] != 3:
                logger.warning(
                    f"RTCVideoStreamTrack: Invalid frame shape: {frame.shape}, "
                    f"expected (H, W, 3), skipping"
                )
                return

            if self.queue.full():
                self.queue.get_nowait()
            self.queue.put_nowait(frame)
            logger.debug(
                f"RTCVideoStreamTrack: Frame added to queue. Queue size: {self.queue.qsize()}, "
                f"shape: {frame.shape}, dtype: {frame.dtype}"
            )
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

    def connect_by_id(self, subordinate_id):
        """Connect to a subordinate using the given ID."""
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

        self.status_queue.put(
            ("connecting", f"Connecting to subordinate {subordinate_id}...")
        )
        asyncio.run_coroutine_threadsafe(
            self._create_peer_connection(subordinate_id), self.loop
        )

    async def _create_peer_connection(self, subordinate_id):
        """Creates and sets up a new RTCPeerConnection."""
        if subordinate_id in self.connections:
            logger.warning(
                f"Connection attempt for existing subordinate {subordinate_id}"
            )
            return

        pc = RTCPeerConnection()
        video_track = RTCVideoStreamTrack()
        pc.addTrack(video_track)

        self.connections[subordinate_id] = {
            "pc": pc,
            "video_track": video_track,
            "status": "connecting",
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
        logger.info(f"Sending offer to {subordinate_id}...")
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

    async def _handle_signaling_message(self, message):
        """Handles incoming messages from the signaling server."""
        data = json.loads(message)
        msg_type = data.get("type")
        source_id = data.get("sourceId")

        logger.info(
            f"Received signaling message of type '{msg_type}' from '{source_id}'"
        )

        if msg_type == "registered":  # Ignore our own registration confirmation
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
