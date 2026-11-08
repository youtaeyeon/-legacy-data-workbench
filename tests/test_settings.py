import json

from hospital_marketing.settings import AppSettings, ProductKeyword, SettingsStore


def test_settings_round_trip_paths_provider_model_and_mock_mode(tmp_path):
    path = tmp_path / "settings.json"
    settings = AppSettings(
        source_dir=tmp_path / "source",
        target_dir=tmp_path / "target",
        provider_id="anthropic",
        model_id="claude-test-model",
        mock_mode=False,
        enabled_extensions=(".xlsx", ".docx"),
        product_keywords=(ProductKeyword("울트라클리어 엘리트", True), ProductKeyword("리뉴비온", False)),
    )

    SettingsStore(path).save(settings)
    loaded = SettingsStore(path).load()

    assert loaded == settings


def test_extension_options_default_to_supported_formats_and_ignore_unknown_settings(tmp_path):
    from hospital_marketing.documents import SUPPORTED_EXTENSIONS

    path = tmp_path / "settings.json"
    assert AppSettings().enabled_extensions == SUPPORTED_EXTENSIONS

    path.write_text('{"enabled_extensions": [".PDF", ".unknown"]}', encoding="utf-8")

    assert SettingsStore(path).load().enabled_extensions == (".pdf",)


def test_settings_file_never_contains_api_key(tmp_path):
    path = tmp_path / "settings.json"
    SettingsStore(path).save(AppSettings(provider_id="openai", model_id="test-model"))

    raw = path.read_text(encoding="utf-8")
    values = json.loads(raw)
    assert "api_key" not in values
    assert "secret-test-key" not in raw


def test_missing_or_invalid_settings_return_safe_defaults(tmp_path):
    path = tmp_path / "settings.json"
    defaults = SettingsStore(path).load()
    assert defaults.provider_id == "local-cli"
    assert defaults.model_id == "claude"
    assert defaults.mock_mode is False
    path.write_text("{not-json", encoding="utf-8")
    assert SettingsStore(path).load() == defaults


def test_existing_ai_settings_are_preserved(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"provider_id":"gemini","model_id":"gemini-3.8-flash","mock_mode":false}',
        encoding="utf-8",
    )

    settings = SettingsStore(path).load()

    assert (settings.provider_id, settings.model_id, settings.mock_mode) == (
        "gemini", "gemini-3.8-flash", False
    )


def test_legacy_settings_without_product_keywords_use_default_products(tmp_path):
    from hospital_marketing.settings import DEFAULT_PRODUCTS

    path = tmp_path / "settings.json"
    path.write_text('{"enabled_extensions": [".xlsx"]}', encoding="utf-8")

    settings = SettingsStore(path).load()

    assert settings.product_keywords == tuple(ProductKeyword(term) for term in DEFAULT_PRODUCTS)


def test_settings_normalize_invalid_product_keywords(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"product_keywords": ['
        '{"term":"  제품 A  ","enabled":false},'
        '{"term":"제품 A","enabled":true},'
        '{"term":"   ","enabled":true},'
        '{"term":"제품 B","enabled":"false"},'
        '"not-an-object"]}',
        encoding="utf-8",
    )

    settings = SettingsStore(path).load()

    assert settings.product_keywords == (ProductKeyword("제품 A", False),)
