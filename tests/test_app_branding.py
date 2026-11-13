from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_020():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "0.2.0"


def test_app_and_dashboard_use_dashboard_branding():
    main_window = (ROOT / "src/hospital_marketing/ui/main_window.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "src/hospital_marketing/outputs/dashboard.py").read_text(encoding="utf-8")

    assert 'self.setWindowTitle(f"병원 마케팅 대시보드 · v{APP_VERSION}")' in main_window
    assert 'QLabel("병원 마케팅 대시보드")' in main_window
    assert "병원별 마케팅 대시보드와 위키·엑셀 자료를 생성합니다." in main_window
    assert "<title>병원 마케팅 대시보드</title>" in dashboard
    assert "🏥 병원 마케팅 대시보드" in dashboard


def test_windows_package_uses_marketing_dashboard_executable_name():
    spec = (ROOT / "hospital-marketing.spec").read_text(encoding="utf-8")
    package_script = (ROOT / "scripts/package_windows.ps1").read_text(encoding="utf-8")

    assert spec.count('name="marketing_dashboard"') == 2
    assert '"marketing_dashboard\\marketing_dashboard.exe"' in package_script


def test_readme_uses_new_executable_name_and_preserves_identifiers():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    settings = (ROOT / "src/hospital_marketing/settings.py").read_text(encoding="utf-8")
    credentials = (ROOT / "src/hospital_marketing/credentials.py").read_text(encoding="utf-8")

    assert "# 병원 마케팅 대시보드" in readme
    assert "dist-win\\marketing_dashboard\\marketing_dashboard.exe" in readme
    assert "hospital-marketing-mvp" in settings
    assert 'SERVICE_NAME = "hospital-marketing-mvp"' in credentials
