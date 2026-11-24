import asyncio
import io
import json
import socket
import unittest
from contextlib import redirect_stdout

from terminal_once import send_arrow_and_print_one_status
from websocket_bridge import WebSocketBridge


class OneShotClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_arrow_and_prints_one_raw_detection_message(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        bridge = WebSocketBridge("127.0.0.1", port)
        bridge.start()
        output = io.StringIO()
        status = {"type": "detection", "frame": 4, "detected": False, "confidence": 0.0}
        expected_raw_status = json.dumps(status, separators=(",", ":"))

        try:
            with redirect_stdout(output):
                client_task = asyncio.create_task(
                    send_arrow_and_print_one_status(f"ws://127.0.0.1:{port}", timeout=2.0)
                )
                arrow = None
                for _ in range(100):
                    arrow = bridge.take_latest_arrow()
                    if arrow is not None:
                        break
                    await asyncio.sleep(0.01)
                self.assertIsNotNone(arrow)
                bridge.publish(status)
                await client_task
        finally:
            bridge.stop()

        self.assertAlmostEqual(arrow["length"], 0.6)
        self.assertAlmostEqual(arrow["dx"], 0.819152, places=5)
        self.assertEqual(output.getvalue(), expected_raw_status + "\n")


if __name__ == "__main__":
    unittest.main()