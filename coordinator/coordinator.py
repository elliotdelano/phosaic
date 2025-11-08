import argparse
import asyncio
import json
import logging

from aiortc import RTCPeerConnection, RTCSessionDescription
from websockets.client import connect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run(pc, websocket):
    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        logger.info("ICE connection state is %s", pc.iceConnectionState)
        if pc.iceConnectionState == "failed":
            await pc.close()

    # Create data channel
    channel = pc.createDataChannel("chat")
    logger.info("Data channel created: %s", channel.label)

    @channel.on("open")
    def on_open():
        logger.info("Data channel is open")
        channel.send("Hello from Python coordinator!")

    @channel.on("message")
    def on_message(message):
        logger.info("Received message: %s", message)

    # Create offer
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    # Send offer
    message = {
        "type": "offer",
        "id": websocket.subordinate_id,
        "offer": {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
    }
    logger.info("Sending offer...")
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
        elif data.get("type") == "ice-candidate":
            candidate_info = data.get("candidate")
            if candidate_info:
                # aiortc needs candidate, sdpMid, sdpMLineIndex
                # sdpMid and sdpMLineIndex might not be present in browser candidates initially
                # but are often needed. We assume the browser sends a complete candidate object.
                await pc.addIceCandidate(candidate_info)
        elif data.get("type") == "registered":
            pass  # Ignore
        else:
            logger.warning("Unknown signaling message type: %s", data.get("type"))


async def main():
    parser = argparse.ArgumentParser(description="Python WebRTC coordinator")
    parser.add_argument("id", help="The ID of the subordinate to connect to")
    args = parser.parse_args()

    uri = "ws://localhost:3000"
    async with connect(uri) as websocket:
        websocket.subordinate_id = args.id

        await websocket.send(
            json.dumps({"type": "register-coordinator", "id": args.id})
        )

        pc = RTCPeerConnection()

        try:
            await run(pc, websocket)
        except KeyboardInterrupt:
            pass
        finally:
            logger.info("Closing connection")
            await pc.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
