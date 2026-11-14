# Build the Windows executable into dist\ElevatorCallTester\ (run on Windows).
$ErrorActionPreference = "Stop"
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.\.venv\Scripts\python.exe -m pip install --quiet -e ".[build]"
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean elevator_call_tester.spec
Write-Host "Built dist\ElevatorCallTester\ElevatorCallTester.exe"
