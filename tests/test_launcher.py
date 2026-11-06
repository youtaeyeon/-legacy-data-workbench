from hospital_marketing_launcher import main


def test_windows_launcher_imports_package_entrypoint():
    assert callable(main)
