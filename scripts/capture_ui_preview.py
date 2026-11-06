from pathlib import Path

from PySide6 import QtGui, QtWidgets

from hospital_marketing.app import create_main_window
from hospital_marketing.settings import AppSettings, SettingsStore


root = Path(__file__).resolve().parents[1]
target = root / "demo-output"
settings = SettingsStore(root / "demo-settings-win.json")
settings.save(
    AppSettings(
        source_dir=root / "fixtures" / "source" / "initial",
        target_dir=target,
        provider_id="mock",
        mock_mode=True,
    )
)
application = QtWidgets.QApplication([])
font_id = QtGui.QFontDatabase.addApplicationFont(r"C:\\Windows\\Fonts\\malgun.ttf")
font = QtGui.QFont("Malgun Gothic") if font_id >= 0 else QtGui.QFont()
application.setFont(font)
window = create_main_window(settings)
window.show()
application.processEvents()
image = window.grab()
preview = target / "ui-preview-windows.png"
preview.parent.mkdir(parents=True, exist_ok=True)
if not image.save(str(preview)):
    raise SystemExit("창 미리보기를 저장하지 못했습니다.")
print(f"saved={preview}\nsize={image.width()}x{image.height()}")
window.close()
application.quit()
