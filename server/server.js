import express from "express";
import http from "http";
import path from "path";
import { fileURLToPath } from "url";
import { WebSocketServer } from "ws";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

const subordinates = new Map();
const coordinators = new Map();

wss.on("connection", (ws) => {
	// Assign a unique ID to every connection
	ws.id = Math.random().toString(36).substring(2, 15);
	console.log(`Client connected with ID: ${ws.id}`);

	ws.on("message", (message) => {
		const data = JSON.parse(message);
		console.log("received: %s", JSON.stringify(data, null, 2));

		switch (data.type) {
			case "register-subordinate":
				subordinates.set(ws.id, ws);
				console.log(`Registered subordinate with ID: ${ws.id}`);
				ws.send(
					JSON.stringify({
						type: "registered",
						id: ws.id,
						width: data.width,
						height: data.height,
					})
				);
				break;

			case "register-coordinator":
				coordinators.set(ws.id, ws);
				console.log(`Registered coordinator with ID: ${ws.id}`);
				ws.send(JSON.stringify({ type: "registered", id: ws.id }));
				break;

			case "offer": {
				const subordinate = subordinates.get(data.targetId);
				if (subordinate) {
					console.log(
						`Forwarding offer from ${data.sourceId} to ${data.targetId}`
					);
					subordinate.send(
						JSON.stringify({
							type: "offer",
							offer: data.offer,
							sourceId: data.sourceId, // Let subordinate know who to reply to
						})
					);
				} else {
					console.log(`Subordinate ${data.targetId} not found`);
				}
				break;
			}

			case "answer": {
				const coordinator = coordinators.get(data.targetId);
				if (coordinator) {
					console.log(
						`Forwarding answer from ${data.sourceId} to ${data.targetId}`
					);
					coordinator.send(
						JSON.stringify({
							type: "answer",
							answer: data.answer,
							sourceId: data.sourceId,
						})
					);
				} else {
					console.log(`Coordinator ${data.targetId} not found`);
				}
				break;
			}

			case "ice-candidate": {
				const targetId = data.targetId;
				// Find the target in either map
				const target =
					coordinators.get(targetId) || subordinates.get(targetId);
				if (target) {
					console.log(
						`Forwarding ICE candidate from ${ws.id} to ${targetId}`
					);
					target.send(
						JSON.stringify({
							type: "ice-candidate",
							candidate: data.candidate,
							sourceId: ws.id,
						})
					);
				} else {
					console.log(`ICE candidate target ${targetId} not found`);
				}
				break;
			}

			default:
				console.log("Unknown message type:", data.type);
		}
	});

	ws.on("close", () => {
		console.log(`Client disconnected: ${ws.id}`);
		// Remove from both maps, it will only be in one
		subordinates.delete(ws.id);
		coordinators.delete(ws.id);
	});
});

const subordinateAppPath = path.join(__dirname, "..", "subordinate");

app.use(express.static(subordinateAppPath));

app.get("/", (req, res) => {
	res.sendFile(path.join(subordinateAppPath, "index.html"));
});

const PORT = process.env.PORT || 3000;

server.listen(PORT, () => {
	console.log(`Server is listening on port ${PORT}`);
});
