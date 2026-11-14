# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec. Build on Windows with build.ps1 (see docs/building.md).

a = Analysis(
    ["elevator_call_tester/__main__.py"],
    pathex=["."],
    datas=[("elevator_call_tester/assets", "elevator_call_tester/assets")],
    hiddenimports=["serial.tools.list_ports"],
    excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ElevatorCallTester",
    icon="elevator_call_tester/assets/icon.ico",
    console=False,  # windowed; __main__ points stdout/stderr at devnull
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ElevatorCallTester")
