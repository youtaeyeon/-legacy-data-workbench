from pathlib import Path


def test_windows_packaging_script_has_utf8_bom_for_powershell_51():
    script = Path(__file__).resolve().parents[1] / "scripts" / "package_windows.ps1"

    assert script.read_bytes().startswith(b"\xef\xbb\xbf")
