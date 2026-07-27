# -*- mode: python ; coding: utf-8 -*-
# Build the Gate Vehicle Counter as a single frozen EXE (no Python on the client).
#   Prereqs on the BUILD machine:  pip install -r vehicle_counter_requirements.txt pyinstaller
#   Put the model file  yolov8n.onnx  next to this .spec (see DPD-VEHICLE-COUNTER.md).
#   Build:               pyinstaller --noconfirm vehicle_counter_agent.spec
#   Output:              dist/vehicle_counter_agent.exe   (self-contained; ~150-250 MB)
import os
from PyInstaller.utils.hooks import collect_submodules, collect_all

hiddenimports = []
hiddenimports += collect_submodules('certifi')

datas = []
binaries = []

# onnxruntime ships native runtime DLLs + capi data — collect_all grabs them so the
# frozen EXE can load the model without a system onnxruntime install.
try:
    _d, _b, _h = collect_all('onnxruntime')
    datas += _d; binaries += _b; hiddenimports += _h
except Exception:
    pass

# Bundle the detection model INTO the exe when present next to this spec. At runtime
# an external yolov8n.onnx placed next to the exe still wins (resolve_model_path),
# so a client can swap/upgrade the model without a rebuild.
if os.path.exists('yolov8n.onnx'):
    datas += [('yolov8n.onnx', '.')]

a = Analysis(
    ['vehicle_counter_agent.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'ultralytics', 'matplotlib', 'pandas', 'scipy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='vehicle_counter_agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
