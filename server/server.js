import express from "express";
import http from "http";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const server = http.createServer(app);

const subordinateAppPath = path.join(__dirname, "..", "subordinate");

app.use(express.static(subordinateAppPath));

app.get("/", (req, res) => {
  res.sendFile(path.join(subordinateAppPath, "index.html"));
});

const PORT = process.env.PORT || 3000;

server.listen(PORT, () => {
  console.log(`Server is listening on port ${PORT}`);
});
