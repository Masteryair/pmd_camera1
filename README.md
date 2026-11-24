# PMD Flexx2 Python environment

## Requirements

- Windows 10/11, 64-bit
- Python 3.10, 64-bit, available through the Windows Python Launcher (`py`)
- The Royale SDK folder `5.16.1.3725` kept beside this README

## Create or recreate the environment

From PowerShell in this folder, run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

The setup script creates `.venv`, installs the pinned Python dependencies and the Royale wheel included in the SDK, and checks that the wrapper imports.

For each new PowerShell session, activate the environment and add Royale's DLL folder to `PATH`:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PATH = "$(Resolve-Path .\5.16.1.3725\bin);$env:PATH"
```

Keep the SDK folder at the same relative path when moving the project. Do not copy `.venv`; run `setup.ps1` on the other computer to recreate it. The target computer also needs a compatible PMD camera driver/runtime installation and the required Visual C++ runtime.

## Run the camera monitor

After setup, activate the environment, add the Royale DLL directory to `PATH` as above, and run:

```powershell
python .\app.py
```

The monitor opens full screen. Press `Esc` or `Q` to close it. The detector accepts markers with either alternating quadrants or two adjacent bright and two adjacent dark quarters. Its default radius search is 6 pixels through one third of the smaller frame dimension; use `--marker-min-radius`, `--marker-max-radius`, and `--marker-min-confidence` to tune it for the camera view.

If no PMD camera is connected, the monitor still opens with a black image, displays the arrow and status panel, and continues accepting WebSocket arrow commands. Detection output reports `detected: false`, XYZ coordinates of 0, and confidence 0 until the camera is available.

## WebSocket messages

The app hosts a WebSocket server at `ws://127.0.0.1:8765` by default. It broadcasts one JSON `detection` message per processed frame. Coordinates are Royale camera-space meters; confidence is a detector score from 0 to 1, not a probability.

To draw an arrow, the other program can send a normalized direction vector and a length fraction:

```json
{"type":"arrow","dx":1,"dy":0.5,"length":0.8}
```

`length` is clamped to 0..1 and scales a maximum of one quarter of the displayed image height. Screen coordinates use positive `dx` to the right and positive `dy` downward. Alternatively, send `angle_deg` instead of `dx`/`dy` (0 degrees points right; positive angles rotate clockwise). Use `{"type":"arrow","dx":0,"dy":0,"length":0}` to clear the arrow. The server acknowledges arrow commands and returns an error message for invalid input.

For a client on another computer, start the monitor with `--ws-host 0.0.0.0` and connect to the host computer's LAN address; allow the selected port through the firewall only for trusted devices.

## Run the terminal companion

Start the camera monitor first. In a second PowerShell window, activate the same environment and run:

```powershell
.\.venv\Scripts\Activate.ps1
python .\terminal_client.py
```

The terminal client prints each detection and sends arrow updates 20 times per second. By default, the arrow length varies sinusoidally between 10% and 100% of its maximum over a 4-second period, while its angle advances by 45 degrees per second. Press `Ctrl+C` to stop it.

Example with a 3-second size period and faster rotation:

```powershell
python .\terminal_client.py --period 3 --angle-speed 90 --min-length 0.05
```

Use `--url ws://127.0.0.1:8765` to select the camera app's WebSocket endpoint, `--send-rate` to change the arrow update rate, and `--status-interval` to control how often the changing arrow parameters are printed.

## One-shot terminal check

To send one fixed arrow command and print one raw detection JSON message, run:

```powershell
python .\terminal_once.py
```

It sends `angle_deg: 35` and `length: 0.6`, skips the arrow acknowledgment, then prints the next detection message exactly as received. Use `--url` to select another endpoint or `--timeout` to change the wait limit.
