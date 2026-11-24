from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed


def arrow_parameters(
    elapsed_seconds: float,
    period_seconds: float,
    min_length: float,
    max_length: float,
    start_angle_deg: float,
    angle_speed_deg_per_second: float,
) -> tuple[float, float]:
    phase = 2.0 * math.pi * elapsed_seconds / period_seconds
    midpoint = (min_length + max_length) / 2.0
    amplitude = (max_length - min_length) / 2.0
    length = midpoint + amplitude * math.sin(phase)
    angle = start_angle_deg + angle_speed_deg_per_second * elapsed_seconds
    return length, angle


def format_detection(message: dict[str, Any]) -> str:
    frame = message.get("frame", "?")
    if not message.get("detected", False):
        position = message.get("position_m")
        if isinstance(position, dict):
            xyz = " ".join(f"{axis.upper()}={_format_number(position.get(axis))}m" for axis in ("x", "y", "z"))
        else:
            xyz = "X=+0.000m Y=+0.000m Z=+0.000m"
        return f"frame={frame} marker=NOT_FOUND {xyz} confidence={float(message.get('confidence', 0.0)):.2f}"

    position = message.get("position_m")
    center = message.get("center_px")
    confidence = float(message.get("confidence", 0.0))
    if isinstance(position, dict):
        xyz = " ".join(f"{axis.upper()}={_format_number(position.get(axis))}m" for axis in ("x", "y", "z"))
    else:
        xyz = "XYZ=unavailable"
    if isinstance(center, dict):
        pixel = f"px=({_format_number(center.get('x'))},{_format_number(center.get('y'))})"
    else:
        pixel = "px=unavailable"
    return f"frame={frame} marker=FOUND {xyz} {pixel} confidence={confidence:.2f}"


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    return f"{number:+.3f}" if math.isfinite(number) else "--"


async def run_client(args: argparse.Namespace) -> None:
    start_time = time.monotonic()
    send_interval = 1.0 / args.send_rate
    next_status_time = 0.0

    print(f"Connecting to camera app at {args.url}", flush=True)
    async with websockets.connect(args.url) as websocket:
        print("Connected. Press Ctrl+C to stop.", flush=True)

        async def send_arrow_commands() -> None:
            nonlocal next_status_time
            while True:
                elapsed = time.monotonic() - start_time
                length, angle = arrow_parameters(
                    elapsed,
                    args.period,
                    args.min_length,
                    args.max_length,
                    args.start_angle,
                    args.angle_speed,
                )
                payload = {"type": "arrow", "angle_deg": angle, "length": length}
                await websocket.send(json.dumps(payload, allow_nan=False, separators=(",", ":")))
                if elapsed >= next_status_time:
                    print(f"arrow angle={angle:.1f}deg length={length:.3f}", flush=True)
                    next_status_time = elapsed + args.status_interval
                await asyncio.sleep(send_interval)

        sender = asyncio.create_task(send_arrow_commands())
        try:
            async for raw_message in websocket:
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    print(f"invalid JSON from camera app: {raw_message}", flush=True)
                    continue
                if not isinstance(message, dict):
                    print(f"unexpected message from camera app: {message!r}", flush=True)
                    continue
                message_type = message.get("type")
                if message_type == "detection":
                    print(format_detection(message), flush=True)
                elif message_type == "error":
                    print(f"camera app error: {message.get('message', 'unknown error')}", flush=True)
        except ConnectionClosed as error:
            print(f"Camera app disconnected: {error}", flush=True)
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print PMD camera detections and animate its overlay arrow")
    parser.add_argument("--url", default="ws://127.0.0.1:8765", help="camera app WebSocket URL")
    parser.add_argument("--send-rate", type=float, default=20.0, help="arrow update rate in messages per second")
    parser.add_argument("--period", type=float, default=4.0, help="sinusoidal arrow-size period in seconds")
    parser.add_argument("--min-length", type=float, default=0.1, help="minimum arrow length fraction (0 to 1)")
    parser.add_argument("--max-length", type=float, default=1.0, help="maximum arrow length fraction (0 to 1)")
    parser.add_argument("--start-angle", type=float, default=0.0, help="starting arrow angle in degrees")
    parser.add_argument("--angle-speed", type=float, default=45.0, help="linear angular speed in degrees per second")
    parser.add_argument("--status-interval", type=float, default=1.0, help="seconds between arrow status lines")
    args = parser.parse_args()

    if args.send_rate <= 0 or not math.isfinite(args.send_rate):
        parser.error("--send-rate must be a positive finite number")
    if args.period <= 0 or not math.isfinite(args.period):
        parser.error("--period must be a positive finite number")
    if not (0 <= args.min_length <= args.max_length <= 1):
        parser.error("expected 0 <= --min-length <= --max-length <= 1")
    if not math.isfinite(args.start_angle) or not math.isfinite(args.angle_speed):
        parser.error("angle values must be finite numbers")
    if args.status_interval <= 0 or not math.isfinite(args.status_interval):
        parser.error("--status-interval must be a positive finite number")
    return args


def main() -> int:
    args = parse_arguments()
    try:
        asyncio.run(run_client(args))
    except KeyboardInterrupt:
        print("Stopped.", flush=True)
    except OSError as error:
        print(f"Could not connect to {args.url}: {error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())