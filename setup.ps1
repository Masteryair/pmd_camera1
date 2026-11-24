$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$wheelPath = Join-Path $projectRoot '5.16.1.3725\python\packages\roypypack-5.16.1.3725-cp310-cp310-win_amd64.whl'
$sdkBin = Join-Path $projectRoot '5.16.1.3725\bin'
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $wheelPath)) {
    throw "Royale wheel not found: $wheelPath"
}
if (-not (Test-Path $sdkBin)) {
    throw "Royale runtime directory not found: $sdkBin"
}

& py -3.10 -c "import struct, sys; assert sys.version_info[:2] == (3, 10); assert struct.calcsize('P') == 8"
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.10 64-bit is required. Install it and ensure the Python Launcher (py.exe) can find it.'
}

if (-not (Test-Path $venvPython)) {
    & py -3.10 -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the virtual environment.' }
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Failed to upgrade pip.' }

& $venvPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Python dependencies.' }

& $venvPython -m pip install $wheelPath
if ($LASTEXITCODE -ne 0) { throw 'Failed to install the Royale Python wrapper.' }

$env:PATH = "$sdkBin;$env:PATH"
& $venvPython -c "from roypypack import roypy; print('Royale Python wrapper loaded successfully')"
if ($LASTEXITCODE -ne 0) {
    throw 'Royale wrapper installed, but could not be imported. Check the Royale runtime DLLs and Visual C++ Redistributable.'
}

Write-Host 'Setup complete. Activate with: .\.venv\Scripts\Activate.ps1'