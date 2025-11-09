let ws = null; // WebSocket will be created after fullscreen
let peerConnection;
let myId;
let coordinatorId; // ID of the coordinator we are talking to
let qrCodeDisplayed = false; // Track if QR code is currently displayed
let refreshHandler = null; // Store the refresh handler function
let displaySize = null; // Store display size captured after fullscreen

const configuration = {
	iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
};

function connectWebSocket() {
	if (ws) {
		return; // Already connected or connecting
	}

	if (!displaySize) {
		console.error("Display size not captured before connection");
		return;
	}

	ws = new WebSocket(`ws://${window.location.host}`);

	ws.onopen = () => {
		console.log("Connected to signaling server");
		// Use display size captured right after fullscreen
		console.log(
			`[Subordinate] Reporting display size: width=${displaySize.width}, height=${displaySize.height}`
		);
		ws.send(
			JSON.stringify({
				type: "register-subordinate",
				width: displaySize.width,
				height: displaySize.height,
			})
		);
	};

	ws.onmessage = async (message) => {
		const data = JSON.parse(message.data);
		console.log("Received signaling message:", data.type);

		switch (data.type) {
			case "registered":
				myId = data.id;
				generateQRCode(data.id);
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
							new RTCIceCandidate(data.candidate)
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

	ws.onclose = () => {
		console.log("Disconnected from signaling server");
	};

	ws.onerror = (error) => {
		console.error("WebSocket error:", error);
	};
}

function isFullscreen() {
	return !!(
		document.fullscreenElement ||
		document.webkitFullscreenElement ||
		document.mozFullScreenElement ||
		document.msFullscreenElement
	);
}

function attemptFullscreen() {
	const element = document.documentElement;
	if (element.requestFullscreen) {
		return element.requestFullscreen().catch((err) => {
			console.log("Fullscreen request failed:", err);
			throw err;
		});
	} else if (element.webkitRequestFullscreen) {
		// Safari
		element.webkitRequestFullscreen();
		return Promise.resolve();
	} else if (element.msRequestFullscreen) {
		// IE/Edge
		element.msRequestFullscreen();
		return Promise.resolve();
	} else if (element.mozRequestFullScreen) {
		// Firefox
		element.mozRequestFullScreen();
		return Promise.resolve();
	}
	return Promise.reject(new Error("Fullscreen not supported"));
}

function exitFullscreen() {
	if (document.exitFullscreen) {
		return document.exitFullscreen().catch((err) => {
			console.log("Exit fullscreen failed:", err);
			throw err;
		});
	} else if (document.webkitExitFullscreen) {
		// Safari
		document.webkitExitFullscreen();
		return Promise.resolve();
	} else if (document.msExitFullscreen) {
		// IE/Edge
		document.msExitFullscreen();
		return Promise.resolve();
	} else if (document.mozCancelFullScreen) {
		// Firefox
		document.mozCancelFullScreen();
		return Promise.resolve();
	}
	return Promise.resolve(); // If not in fullscreen, resolve immediately
}

async function checkFullscreenAndConnect() {
	if (isFullscreen()) {
		// Already in fullscreen, wait for it to complete sizing
		hideFullscreenPrompt();
		await waitForFullscreenComplete();
		await handleFullscreenComplete();
	} else {
		// Not in fullscreen, show prompt and wait for user interaction
		showFullscreenPrompt();
	}
}

function waitForFullscreenComplete() {
	return new Promise((resolve) => {
		// Wait for fullscreen change event
		const checkFullscreen = () => {
			if (isFullscreen()) {
				// Wait for browser to finish resizing - use requestAnimationFrame to ensure layout is complete
				requestAnimationFrame(() => {
					requestAnimationFrame(() => {
						// Double RAF ensures layout is complete
						resolve();
					});
				});
			}
		};

		// Check immediately in case we're already in fullscreen
		if (isFullscreen()) {
			checkFullscreen();
		} else {
			// Listen for fullscreen change
			const handler = () => {
				checkFullscreen();
				// Remove listeners after resolving
				document.removeEventListener("fullscreenchange", handler);
				document.removeEventListener("webkitfullscreenchange", handler);
				document.removeEventListener("mozfullscreenchange", handler);
				document.removeEventListener("MSFullscreenChange", handler);
			};

			document.addEventListener("fullscreenchange", handler);
			document.addEventListener("webkitfullscreenchange", handler);
			document.addEventListener("mozfullscreenchange", handler);
			document.addEventListener("MSFullscreenChange", handler);
		}
	});
}

function showFullscreenPrompt() {
	const prompt = document.getElementById("fullscreen-prompt");
	prompt.classList.remove("hidden");

	// Add click/touch handler to enter fullscreen
	const handleInteraction = async () => {
		try {
			await attemptFullscreen();
			// Wait for fullscreen to complete and browser to finish resizing
			await waitForFullscreenComplete();
			// Now capture display size and connect
			await handleFullscreenComplete();
		} catch (err) {
			console.error("Failed to enter fullscreen:", err);
		}
	};

	prompt.onclick = handleInteraction;
	prompt.ontouchstart = handleInteraction;
}

function hideFullscreenPrompt() {
	const prompt = document.getElementById("fullscreen-prompt");
	prompt.classList.add("hidden");
	prompt.onclick = null;
	prompt.ontouchstart = null;
}

async function handleFullscreenComplete() {
	hideFullscreenPrompt();

	//wait for system animations outside the browser to complete
	await new Promise((resolve) => setTimeout(resolve, 200));

	// Capture display size after fullscreen has finished resizing
	displaySize = {
		width: window.innerWidth,
		height: window.innerHeight,
	};
	console.log(
		`[Subordinate] Captured display size after fullscreen: width=${displaySize.width}, height=${displaySize.height}`
	);
	// Enable refresh on tap when entering fullscreen
	enableRefreshOnTap();
	// Connect WebSocket after capturing display size
	connectWebSocket();
}

function handleFullscreenChange() {
	if (isFullscreen()) {
		// Only handle if not already processing (to avoid duplicate calls)
		if (!displaySize) {
			waitForFullscreenComplete().then(() => {
				handleFullscreenComplete();
			});
		} else {
			// Already initialized, just enable refresh on tap
			enableRefreshOnTap();
		}
	} else {
		// Exited fullscreen, disable refresh on tap
		disableRefreshOnTap();
	}
}

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
	qrCodeDisplayed = true;
	// Refresh on tap is already enabled in handleFullscreenComplete()
}

function enableRefreshOnTap() {
	// Remove any existing handler first to avoid duplicates
	disableRefreshOnTap();

	// Create handler that exits fullscreen then refreshes the page
	refreshHandler = async () => {
		// Only refresh if we're in fullscreen
		if (isFullscreen()) {
			// Disable the handler immediately to prevent multiple taps
			disableRefreshOnTap();

			try {
				await exitFullscreen();
				// Wait a brief moment for fullscreen to fully exit
				setTimeout(() => {
					window.location.reload();
				}, 100);
			} catch (err) {
				console.error("Failed to exit fullscreen:", err);
				// Refresh anyway even if exit failed
				window.location.reload();
			}
		}
	};

	// Add event listeners for both click and touch
	document.addEventListener("click", refreshHandler);
	document.addEventListener("touchend", refreshHandler);
}

function disableRefreshOnTap() {
	if (refreshHandler) {
		document.removeEventListener("click", refreshHandler);
		document.removeEventListener("touchend", refreshHandler);
		refreshHandler = null;
	}
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
			qrCodeDisplayed = false;
			// Don't disable refresh on tap - keep it active while in fullscreen
			console.log(
				"Video element srcObject set with new MediaStream. Attempting to play..."
			);

			// Mute the video element to allow autoplay in most browsers
			videoElement.muted = true;

			videoElement
				.play()
				.then(() => {
					// Log the actual video element and stream size after play
					setTimeout(() => {
						const vw = videoElement.videoWidth;
						const vh = videoElement.videoHeight;
						const styleW = videoElement.offsetWidth;
						const styleH = videoElement.offsetHeight;
						console.log(
							`[Subordinate] Video element videoWidth=${vw}, videoHeight=${vh}`
						);
						console.log(
							`[Subordinate] Video element offsetWidth=${styleW}, offsetHeight=${styleH}`
						);
					}, 500);
				})
				.catch((e) => {
					console.error("Video play failed:", e);
				});
		}
	};

	peerConnection.onicecandidate = (event) => {
		if (event.candidate && ws) {
			// Send candidate to the coordinator that sent the offer
			ws.send(
				JSON.stringify({
					type: "ice-candidate",
					candidate: event.candidate,
					targetId: coordinatorId,
				})
			);
		}
	};

	peerConnection.ondatachannel = (event) => {
		const receiveChannel = event.channel;
		receiveChannel.onopen = () => {
			console.log("Data channel is open!");
			// Send subordinate-info with display size via data channel
			const width = window.innerWidth;
			const height = window.innerHeight;
			const infoMsg = JSON.stringify({
				type: "subordinate-info",
				width,
				height,
			});
			receiveChannel.send(infoMsg);
			receiveChannel.send("Hello from subordinate!");
		};
		receiveChannel.onmessage = (event) => {
			console.log("Message received:", event.data);
		};
	};

	try {
		await peerConnection.setRemoteDescription(
			new RTCSessionDescription(offer)
		);
		const answer = await peerConnection.createAnswer();
		await peerConnection.setLocalDescription(answer);

		// Send the answer back to the specific coordinator
		if (ws) {
			ws.send(
				JSON.stringify({
					type: "answer",
					answer: answer,
					targetId: coordinatorId,
					sourceId: myId,
				})
			);
		}
	} catch (error) {
		console.error("Error handling offer:", error);
	}
}

// Listen for fullscreen changes
document.addEventListener("fullscreenchange", handleFullscreenChange);
document.addEventListener("webkitfullscreenchange", handleFullscreenChange);
document.addEventListener("mozfullscreenchange", handleFullscreenChange);
document.addEventListener("MSFullscreenChange", handleFullscreenChange);

// Check fullscreen status on load and show prompt if needed
window.addEventListener("load", () => {
	setQRCodeSize();
	checkFullscreenAndConnect();
});

window.addEventListener("resize", setQRCodeSize);
