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

function generateUniqueId() {
  return Math.random().toString(36).substring(2, 15);
}

wss.on("connection", (ws) => {
  console.log("Client connected");

  ws.on("message", (message) => {
    const data = JSON.parse(message);
    console.log("received: %s", JSON.stringify(data, null, 2));

    switch (data.type) {
      case "register-subordinate": {
        const id = generateUniqueId();
        ws.id = id;
        subordinates.set(id, ws);
        console.log(`Subordinate registered with id ${id}`);
        ws.send(JSON.stringify({ type: "registered", id: id }));
        break;
      }
      case "register-coordinator": {
        const id = data.id;
        ws.id = id;
        coordinators.set(id, ws);
        console.log(`Coordinator registered for id ${id}`);
        break;
      }
      case "offer": {
        const subordinate = subordinates.get(data.id);
        if (subordinate) {
          console.log(`Forwarding offer to subordinate ${data.id}`);
          subordinate.send(
            JSON.stringify({ type: "offer", offer: data.offer }),
          );
        } else {
          console.log(`Subordinate ${data.id} not found`);
        }
        break;
      }
      case "answer": {
        const coordinator = coordinators.get(data.id);
        if (coordinator) {
          console.log(`Forwarding answer to coordinator for ${data.id}`);
          coordinator.send(
            JSON.stringify({ type: "answer", answer: data.answer }),
          );
        } else {
          console.log(`Coordinator for ${data.id} not found`);
        }
        break;
      }
      case "ice-candidate": {
        const target = subordinates.has(data.id)
          ? subordinates.get(data.id)
          : coordinators.get(data.id);
        const source = subordinates.has(ws.id) ? "subordinate" : "coordinator";

        if (target) {
          console.log(`Forwarding ICE candidate to ${data.id} from ${source}`);
          target.send(
            JSON.stringify({
              type: "ice-candidate",
              candidate: data.candidate,
            }),
          );
        }
        break;
      }
      default:
        console.log("Unknown message type:", data.type);
    }
  });

  ws.on("close", () => {
    console.log("Client disconnected");
    if (subordinates.has(ws.id)) {
      subordinates.delete(ws.id);
      console.log(`Subordinate ${ws.id} unregistered`);
    }
    if (coordinators.has(ws.id)) {
      coordinators.delete(ws.id);
      console.log(`Coordinator for ${ws.id} unregistered`);
    }
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
