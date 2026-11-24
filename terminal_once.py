import argparse
import asyncio
import json

import websockets


ARROW_MESSAGE = {"type": "arrow", "angle_deg": 35.0, "length": 0.6}


async def send_arrow_and_print_one_status(url: str, timeout: float) -> None:
    async with websockets.connect(url) as websocket:
        await websocket.send(json.dumps(ARROW_MESSAGE, separators=(",", ":")))
        deadline = asyncio.get_running_loop().time() + timeout

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for a detection status")
            raw_message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict) or message.get("type") == "ack":
                continue
            if message.get("type") in ("detection", "error"):
                print(raw_message, flush=True)
                return


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one arrow command and print one raw camera status")
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    try:
        asyncio.run(send_arrow_and_print_one_status(args.url, args.timeout))
    except (OSError, TimeoutError, asyncio.TimeoutError) as error:
        parser.exit(1, f"Unable to read camera status: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())