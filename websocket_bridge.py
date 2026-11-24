from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
from queue import Empty, Full, Queue
from typing import Any

import websockets


logger = logging.getLogger(__name__)


class WebSocketBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: Any = None
        self._outgoing: asyncio.Queue[str] | None = None
        self._clients: set[Any] = set()
        self._sender_task: asyncio.Task[None] | None = None
        self._arrow_queue: Queue[dict[str, float]] = Queue(maxsize=1)
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._startup_error: Exception | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="websocket-server", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Timed out while starting the WebSocket server")
        if self._startup_error is not None:
            raise RuntimeError(f"Could not start WebSocket server: {self._startup_error}") from self._startup_error

    def stop(self) -> None:
        if self._loop is None or self._thread is None or not self._thread.is_alive():
            return
        future = asyncio.run_coroutine_threadsafe(self._close_server(), self._loop)
        try:
            future.result(timeout=3)
        except Exception:
            logger.exception("Error while closing the WebSocket server")
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3)

    def publish(self, message: dict[str, Any]) -> None:
        if self._loop is None or self._outgoing is None or not self._thread or not self._thread.is_alive():
            return
        encoded = json.dumps(message, allow_nan=False, separators=(",", ":"))
        self._loop.call_soon_threadsafe(self._enqueue_latest, encoded)

    def take_latest_arrow(self) -> dict[str, float] | None:
        latest = None
        while True:
            try:
                latest = self._arrow_queue.get_nowait()
            except Empty:
                return latest

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._outgoing = asyncio.Queue(maxsize=1)
        try:
            self._loop.run_until_complete(self._start_server())
            self._sender_task = self._loop.create_task(self._broadcast_loop())
        except Exception as error:
            self._startup_error = error
            self._ready.set()
            self._loop.close()
            return

        self._ready.set()
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()

    async def _start_server(self) -> None:
        self._server = await websockets.serve(self._handle_client, self.host, self.port)

    async def _handle_client(self, websocket: Any, _path: str | None = None) -> None:
        self._clients.add(websocket)
        logger.info("WebSocket client connected")
        try:
            async for raw_message in websocket:
                try:
                    message = json.loads(raw_message)
                    arrow = self._parse_arrow(message)
                except (json.JSONDecodeError, TypeError, ValueError) as error:
                    await websocket.send(json.dumps({"type": "error", "message": str(error)}))
                    continue
                self._put_latest_arrow(arrow)
                await websocket.send(json.dumps({"type": "ack", "command": "arrow"}))
        finally:
            self._clients.discard(websocket)
            logger.info("WebSocket client disconnected")

    @staticmethod
    def _parse_arrow(message: Any) -> dict[str, float]:
        if not isinstance(message, dict) or message.get("type") != "arrow":
            raise ValueError('Expected an object with type "arrow"')

        if "angle_deg" in message:
            angle = math.radians(_finite_number(message["angle_deg"], "angle_deg"))
            dx, dy = math.cos(angle), math.sin(angle)
        else:
            dx = _finite_number(message.get("dx"), "dx")
            dy = _finite_number(message.get("dy"), "dy")

        magnitude = math.hypot(dx, dy)
        if magnitude > 0:
            dx /= magnitude
            dy /= magnitude
        length = min(1.0, max(0.0, _finite_number(message.get("length", 1.0), "length")))
        return {"dx": dx, "dy": dy, "length": length}

    def _put_latest_arrow(self, arrow: dict[str, float]) -> None:
        try:
            self._arrow_queue.put_nowait(arrow)
        except Full:
            try:
                self._arrow_queue.get_nowait()
            except Empty:
                pass
            self._arrow_queue.put_nowait(arrow)

    def _enqueue_latest(self, message: str) -> None:
        assert self._outgoing is not None
        if self._outgoing.full():
            try:
                self._outgoing.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._outgoing.put_nowait(message)

    async def _broadcast_loop(self) -> None:
        assert self._outgoing is not None
        while True:
            message = await self._outgoing.get()
            clients = tuple(self._clients)
            if not clients:
                continue
            results = await asyncio.gather(
                *(asyncio.wait_for(client.send(message), timeout=0.5) for client in clients),
                return_exceptions=True,
            )
            for client, result in zip(clients, results):
                if isinstance(result, Exception):
                    self._clients.discard(client)
                    asyncio.create_task(client.close())

    async def _close_server(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for client in tuple(self._clients):
            await client.close()
        if self._sender_task is not None:
            self._sender_task.cancel()
            await asyncio.gather(self._sender_task, return_exceptions=True)


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result