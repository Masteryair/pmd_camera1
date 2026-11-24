import asyncio
import socket
import unittest

import websockets

from websocket_bridge import WebSocketBridge


class WebSocketBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.bridge = WebSocketBridge("127.0.0.1", port)
        self.bridge.start()
        self.uri = f"ws://127.0.0.1:{port}"

    async def asyncTearDown(self) -> None:
        self.bridge.stop()

    async def test_arrow_command_is_normalized_and_clamped(self) -> None:
        async with websockets.connect(self.uri) as client:
            await client.send('{"type":"arrow","dx":3,"dy":4,"length":2}')
            await client.recv()

        arrow = self.bridge.take_latest_arrow()
        self.assertIsNotNone(arrow)
        assert arrow is not None
        self.assertAlmostEqual(arrow["dx"], 0.6)
        self.assertAlmostEqual(arrow["dy"], 0.8)
        self.assertEqual(arrow["length"], 1.0)

    async def test_detection_is_broadcast_to_clients(self) -> None:
        async with websockets.connect(self.uri) as client:
            await client.send('{"type":"arrow","dx":0,"dy":0,"length":0}')
            await client.recv()
            self.bridge.publish({"type": "detection", "detected": False})
            message = await asyncio.wait_for(client.recv(), timeout=1.0)

        self.assertEqual(message, '{"type":"detection","detected":false}')


if __name__ == "__main__":
    unittest.main()