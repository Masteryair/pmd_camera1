import argparse
import asyncio
import io
import math
import socket
import unittest
from contextlib import redirect_stdout

from terminal_client import arrow_parameters, format_detection, run_client
from websocket_bridge import WebSocketBridge


class TerminalClientTests(unittest.TestCase):
    def test_arrow_length_follows_sine_and_angle_advances_linearly(self) -> None:
        length_start, angle_start = arrow_parameters(0, 4, 0.1, 1.0, 10, 45)
        length_peak, angle_later = arrow_parameters(1, 4, 0.1, 1.0, 10, 45)
        length_halfway, _ = arrow_parameters(2, 4, 0.1, 1.0, 10, 45)

        self.assertAlmostEqual(length_start, 0.55)
        self.assertAlmostEqual(length_peak, 1.0)
        self.assertAlmostEqual(length_halfway, 0.55)
        self.assertEqual(angle_start, 10)
        self.assertEqual(angle_later, 55)

    def test_formats_detection_coordinates(self) -> None:
        message = {
            "frame": 17,
            "detected": True,
            "position_m": {"x": 0.12, "y": -0.08, "z": 1.4},
            "center_px": {"x": 120.5, "y": 84},
            "confidence": 0.87,
        }

        line = format_detection(message)

        self.assertIn("frame=17", line)
        self.assertIn("X=+0.120m", line)
        self.assertIn("Y=-0.080m", line)
        self.assertIn("Z=+1.400m", line)
        self.assertIn("confidence=0.87", line)

    def test_formats_missing_detection(self) -> None:
        self.assertEqual(
            format_detection(
                {
                    "frame": 3,
                    "detected": False,
                    "position_m": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "confidence": 0.0,
                }
            ),
            "frame=3 marker=NOT_FOUND X=+0.000m Y=+0.000m Z=+0.000m confidence=0.00",
        )


class TerminalClientIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_prints_detection_from_camera_websocket(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        bridge = WebSocketBridge("127.0.0.1", port)
        bridge.start()
        output = io.StringIO()
        args = argparse.Namespace(
            url=f"ws://127.0.0.1:{port}",
            send_rate=10.0,
            period=4.0,
            min_length=0.1,
            max_length=1.0,
            start_angle=0.0,
            angle_speed=45.0,
            status_interval=10.0,
        )

        try:
            with redirect_stdout(output):
                client_task = asyncio.create_task(run_client(args))
                await asyncio.sleep(0.2)
                bridge.publish(
                    {
                        "type": "detection",
                        "frame": 8,
                        "detected": True,
                        "position_m": {"x": 0.1, "y": -0.2, "z": 1.3},
                        "center_px": {"x": 40, "y": 30},
                        "confidence": 0.9,
                    }
                )
                await asyncio.sleep(0.1)
                client_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await client_task
        finally:
            bridge.stop()

        self.assertIn("frame=8 marker=FOUND", output.getvalue())
        self.assertIn("X=+0.100m", output.getvalue())


if __name__ == "__main__":
    unittest.main()