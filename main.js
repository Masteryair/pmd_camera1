const URL = "ws://127.0.0.1:8765";
const ARROW_MESSAGE = { type: "arrow", angle_deg: 135.0, length: 0.6 };

const ws = new WebSocket(URL);

ws.addEventListener("open", () => {
  ws.send(JSON.stringify(ARROW_MESSAGE));
});

ws.addEventListener("message", ({ data }) => {
  const raw = typeof data === "string" ? data : data.toString();
  const msg = JSON.parse(raw);
  if (msg.type === "detection" || msg.type === "error") {
    console.log(raw);
    ws.close();
  }
});