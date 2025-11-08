const ws = new WebSocket(`ws://${window.location.host}`);
let peerConnection;
let myId;
let coordinatorId; // ID of the coordinator we are talking to

const configuration = {
  iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
};

ws.onopen = () => {
  console.log("Connected to signaling server");
  ws.send(JSON.stringify({ type: "register-subordinate" }));
};

ws.onmessage = async (message) => {
  const data = JSON.parse(message.data);
  console.log("Received signaling message:", data.type);

  switch (data.type) {
    case "registered":
      myId = data.id;
      generateQRCode(myId);
      break;
    case "offer":
      // When we get an offer, store the sender's ID (the coordinator's ID)
      coordinatorId = data.sourceId;
      await handleOffer(data.offer);
      break;
    case "ice-candidate":
      if (peerConnection) {
        try {
          await peerConnection.addIceCandidate(
            new RTCIceCandidate(data.candidate),
          );
        } catch (e) {
          console.error("Error adding received ice candidate", e);
        }
      }
      break;
    default:
      console.log("Unknown message type:", data.type);
  }
};

function setQRCodeSize() {
  const qrCodeElement = document.getElementById("qrcode");
  const size = Math.min(window.innerWidth, window.innerHeight) * 0.9;
  qrCodeElement.style.width = size + "px";
  qrCodeElement.style.height = size + "px";
}

function generateQRCode(id) {
  const qrData = JSON.stringify({ id: id });
  const qr = qrcode(0, "H");
  qr.addData(qrData);
  qr.make();
  const qrCodeElement = document.getElementById("qrcode");
  qrCodeElement.innerHTML = qr.createImgTag(10, 0);
  setQRCodeSize();
}

async function handleOffer(offer) {
  peerConnection = new RTCPeerConnection(configuration);

  peerConnection.ontrack = (event) => {
    console.log("Track received:", event.track.kind);
    const videoElement = document.getElementById("video");
    const qrCodeElement = document.getElementById("qrcode");

    if (event.track.kind === "video") {
      // Create a new MediaStream and add the received track to it.
      const newStream = new MediaStream([event.track]);
      videoElement.srcObject = newStream;

      qrCodeElement.style.display = "none";
      videoElement.style.display = "block";
      console.log(
        "Video element srcObject set with new MediaStream. Attempting to play...",
      );

      // Mute the video element to allow autoplay in most browsers
      videoElement.muted = true;

      videoElement.play().catch((e) => {
        console.error("Video play failed:", e);
      });
    }
  };

  peerConnection.onicecandidate = (event) => {
    if (event.candidate) {
      // Send candidate to the coordinator that sent the offer
      ws.send(
        JSON.stringify({
          type: "ice-candidate",
          candidate: event.candidate,
          targetId: coordinatorId,
        }),
      );
    }
  };

  peerConnection.ondatachannel = (event) => {
    const receiveChannel = event.channel;
    receiveChannel.onopen = () => {
      console.log("Data channel is open!");
      receiveChannel.send("Hello from subordinate!");
    };
    receiveChannel.onmessage = (event) => {
      console.log("Message received:", event.data);
    };
  };

  try {
    await peerConnection.setRemoteDescription(new RTCSessionDescription(offer));
    const answer = await peerConnection.createAnswer();
    await peerConnection.setLocalDescription(answer);

    // Send the answer back to the specific coordinator
    ws.send(
      JSON.stringify({
        type: "answer",
        answer: answer,
        targetId: coordinatorId,
        sourceId: myId,
      }),
    );
  } catch (error) {
    console.error("Error handling offer:", error);
  }
}

ws.onclose = () => {
  console.log("Disconnected from signaling server");
};

ws.onerror = (error) => {
  console.error("WebSocket error:", error);
};

// Set initial QR code size and update on resize
window.addEventListener("load", setQRCodeSize);
window.addEventListener("resize", setQRCodeSize);
