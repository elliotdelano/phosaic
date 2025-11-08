import argparse
import asyncio
import json
import logging
import queue
import threading

from aiortc import RTCPeerConnection, RTCSessionDescription
from websockets.client import connect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Coordinator:
    """WebRTC Coordinator for establishing peer connections via QR code IDs."""

    def __init__(self):
        self.status_queue = queue.Queue()
        self.is_connected = False
        self.current_id = None

    def connect_by_id(self, subordinate_id):
        """Connect to a subordinate using the given ID."""
        self.current_id = subordinate_id
        self.status_queue.put(
            ("connecting", f"Connecting to subordinate {subordinate_id}...")
        )

        # Run the connection in a separate thread to avoid blocking
        thread = threading.Thread(target=self._run_connection, args=(subordinate_id,))
        thread.daemon = True
        thread.start()

    def _run_connection(self, subordinate_id):
        """Run the WebRTC connection logic in a separate thread."""
        try:
            asyncio.run(self._connect_async(subordinate_id))
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.status_queue.put(("error", f"Connection failed: {e}"))

    async def _connect_async(self, subordinate_id):
        """Asynchronous connection logic."""
        uri = "ws://localhost:3000"
        self.coordinator_id = None

        try:
            async with connect(uri) as websocket:
                # 1. Register and get our own ID
                await websocket.send(json.dumps({"type": "register-coordinator"}))

                # Wait for the registration confirmation
                message = await websocket.recv()
                data = json.loads(message)
                if data.get("type") == "registered":
                    self.coordinator_id = data["id"]
                    self.status_queue.put(
                        (
                            "registered",
                            f"Registered with server. Coordinator ID: {self.coordinator_id}",
                        )
                    )
                    logger.info(
                        f"Registered with server. Coordinator ID: {self.coordinator_id}"
                    )
                else:
                    logger.error(f"Failed to register with server. Response: {data}")
                    self.status_queue.put(("error", "Failed to register with server"))
                    return

                # 2. Proceed with connection logic
                pc = RTCPeerConnection()
                websocket.subordinate_id = (
                    subordinate_id  # Keep track of who we are calling
                )

                try:
                    await self.run(pc, websocket)
                except KeyboardInterrupt:
                    pass
                finally:
                    logger.info("Closing connection")
                    await pc.close()

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.status_queue.put(("error", f"WebSocket connection failed: {e}"))

    async def run(self, pc, websocket):
        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logger.info("ICE connection state is %s", pc.iceConnectionState)
            if pc.iceConnectionState == "failed":
                await pc.close()
                self.status_queue.put(("failed", "ICE connection failed"))
            elif pc.iceConnectionState == "connected":
                self.is_connected = True
                self.status_queue.put(
                    ("connected", f"Connected to subordinate {self.current_id}")
                )
            elif pc.iceConnectionState == "disconnected":
                self.is_connected = False
                self.status_queue.put(("disconnected", "Connection lost"))

        # Create data channel
        channel = pc.createDataChannel("chat")
        logger.info("Data channel created: %s", channel.label)

        @channel.on("open")
        def on_open():
            logger.info("Data channel is open")
            channel.send("Hello from Python coordinator!")
            self.status_queue.put(("channel_open", "Data channel opened"))

        @channel.on("message")
        def on_message(message):
            logger.info("Received message: %s", message)
            self.status_queue.put(("message", f"Received: {message}"))

        # Create offer
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        # Send offer with explicit source and target IDs
        message = {
            "type": "offer",
            "sourceId": self.coordinator_id,
            "targetId": websocket.subordinate_id,
            "offer": {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
        }
        logger.info(f"Sending offer to {websocket.subordinate_id}...")
        self.status_queue.put(("offer_sent", "WebRTC offer sent"))
        await websocket.send(json.dumps(message))

        # Listen for messages from signaling server
        async for message in websocket:
            data = json.loads(message)
            logger.info("Received signaling message: %s", data.get("type"))

            if data.get("type") == "answer":
                answer = RTCSessionDescription(
                    sdp=data["answer"]["sdp"], type=data["answer"]["type"]
                )
                await pc.setRemoteDescription(answer)
                self.status_queue.put(("answer_received", "WebRTC answer received"))
            elif data.get("type") == "ice-candidate":
                candidate_info = data.get("candidate")
                if candidate_info:
                    await pc.addIceCandidate(candidate_info)
            elif data.get("type") == "registered":
                pass  # This is our own registration, ignore
            else:
                logger.warning("Unknown signaling message type: %s", data.get("type"))

    def get_status(self):
        """Get the latest status update if available."""
        try:
            return self.status_queue.get_nowait()
        except queue.Empty:
            return None


def main():
    parser = argparse.ArgumentParser(description="Python WebRTC coordinator")
    parser.add_argument("id", help="The ID of the subordinate to connect to")
    args = parser.parse_args()

    # Use the Coordinator class for command line usage
    coordinator = Coordinator()
    coordinator.connect_by_id(args.id)

    # Keep the program running to monitor status
    try:
        while True:
            status = coordinator.get_status()
            if status:
                print(f"Status: {status[0]} - {status[1]}")
            import time

            time.sleep(0.1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
