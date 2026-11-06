from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

project_root = Path(SPECPATH)
source = project_root / "src"
a = Analysis(
    [str(source / "hospital_marketing_launcher.py")],
    pathex=[str(source)],
    binaries=[],
    datas=copy_metadata("hospital-marketing-mvp"),
    hiddenimports=["keyring.backends.Windows"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HospitalMarketingMVP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="HospitalMarketingMVP",
)
