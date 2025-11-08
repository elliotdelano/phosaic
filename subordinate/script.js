const ws = new WebSocket(`ws://${window.location.host}`);
let peerConnection;
let uniqueId;

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
      uniqueId = data.id;
      generateQRCode(uniqueId);
      break;
    case "offer":
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

function generateQRCode(id) {
  const qrData = JSON.stringify({ id: id });
  const qr = qrcode(0, "H");
  qr.addData(qrData);
  qr.make();
  const qrCodeElement = document.getElementById("qrcode");
  qrCodeElement.innerHTML = qr.createImgTag(10, 0);
}

async function handleOffer(offer) {
  peerConnection = new RTCPeerConnection(configuration);

  peerConnection.onicecandidate = (event) => {
    if (event.candidate) {
      ws.send(
        JSON.stringify({
          type: "ice-candidate",
          candidate: event.candidate,
          id: uniqueId,
        }),
      );
    }
  };

  peerConnection.ondatachannel = (event) => {
    const receiveChannel = event.channel;
    receiveChannel.onopen = () => {
      console.log("Data channel is open!");
      document.getElementById("qrcode").innerHTML =
        "<p>Connection established!</p>";
    };
    receiveChannel.onmessage = (event) => {
      console.log("Message received:", event.data);
      const messageElement = document.createElement("p");
      messageElement.textContent = `Received: ${event.data}`;
      document.getElementById("qrcode").appendChild(messageElement);
    };
  };

  try {
    await peerConnection.setRemoteDescription(new RTCSessionDescription(offer));
    const answer = await peerConnection.createAnswer();
    await peerConnection.setLocalDescription(answer);
    ws.send(JSON.stringify({ type: "answer", answer: answer, id: uniqueId }));
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
