import json
from unittest.mock import patch

from localdictate import settings


def test_defaults_when_no_file(tmp_path):
    fake = tmp_path / "nonexistent" / "settings.json"
    with (
        patch.object(settings, "_config_file", fake),
        patch.object(settings, "_old_config_file", tmp_path / "old.json"),
    ):
        cfg = settings.load()
    assert cfg == settings.DEFAULTS


def test_default_device_is_cpu():
    # CPU works on every machine; GPU is opt-in via Settings.
    assert settings.DEFAULTS["device"] == "cpu"


def test_save_and_load_roundtrip(tmp_path):
    cfg_file = tmp_path / "settings.json"
    with (
        patch.object(settings, "_config_file", cfg_file),
        patch.object(settings, "_config_dir", tmp_path),
        patch.object(settings, "_old_config_file", tmp_path / "old.json"),
    ):
        settings.save({"model": "large-v3", "hotkey": "alt+d"})
        cfg = settings.load()
    assert cfg["model"] == "large-v3"
    assert cfg["hotkey"] == "alt+d"
    assert cfg["autostart"] is False  # default merged


def test_corrupt_json_falls_back_to_defaults(tmp_path):
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text("{invalid json")
    with (
        patch.object(settings, "_config_file", cfg_file),
        patch.object(settings, "_config_dir", tmp_path),
        patch.object(settings, "_old_config_file", tmp_path / "old.json"),
    ):
        cfg = settings.load()
    assert cfg == settings.DEFAULTS


def test_non_dict_json_falls_back_to_defaults(tmp_path):
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text("[]")
    with (
        patch.object(settings, "_config_file", cfg_file),
        patch.object(settings, "_config_dir", tmp_path),
        patch.object(settings, "_old_config_file", tmp_path / "old.json"),
    ):
        cfg = settings.load()
    assert cfg == settings.DEFAULTS


def test_migration_from_valid_old_config(tmp_path):
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    old_file = old_dir / "settings.json"
    old_file.write_text(json.dumps({"model": "large-v3", "hotkey": "ctrl+a"}))

    new_file = tmp_path / "new" / "settings.json"
    new_dir = tmp_path / "new"

    with (
        patch.object(settings, "_config_file", new_file),
        patch.object(settings, "_config_dir", new_dir),
        patch.object(settings, "_old_config_file", old_file),
    ):
        cfg = settings.load()

    assert cfg["model"] == "large-v3"
    assert cfg["hotkey"] == "ctrl+a"
    # New file should have been created
    assert new_file.exists()


def test_migration_from_corrupt_old_config(tmp_path):
    old_file = tmp_path / "old.json"
    old_file.write_text("not json at all")

    new_file = tmp_path / "new" / "settings.json"

    with (
        patch.object(settings, "_config_file", new_file),
        patch.object(settings, "_config_dir", tmp_path / "new"),
        patch.object(settings, "_old_config_file", old_file),
    ):
        cfg = settings.load()

    assert cfg == settings.DEFAULTS
    assert not new_file.exists()  # no corrupt file propagated


def test_invalid_hotkey_falls_back_to_default(tmp_path):
    cfg_file = tmp_path / "settings.json"
    # Modifier-only hotkey is invalid
    cfg_file.write_text(json.dumps({"hotkey": "ctrl"}))
    with (
        patch.object(settings, "_config_file", cfg_file),
        patch.object(settings, "_config_dir", tmp_path),
        patch.object(settings, "_old_config_file", tmp_path / "old.json"),
    ):
        cfg = settings.load()
    assert cfg["hotkey"] == settings.DEFAULTS["hotkey"]


def test_empty_hotkey_falls_back_to_default(tmp_path):
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps({"hotkey": ""}))
    with (
        patch.object(settings, "_config_file", cfg_file),
        patch.object(settings, "_config_dir", tmp_path),
        patch.object(settings, "_old_config_file", tmp_path / "old.json"),
    ):
        cfg = settings.load()
    assert cfg["hotkey"] == settings.DEFAULTS["hotkey"]


def test_label_for_model():
    assert settings.label_for_model("distil-medium.en") == "Balanced"
    assert settings.label_for_model("unknown-model") == "unknown-model"


def test_model_for_label():
    assert settings.model_for_label("Fast") == "distil-small.en"
    assert settings.model_for_label("custom-id") == "custom-id"


def test_validate_hotkey():
    assert settings.validate_hotkey("ctrl+space") is True
    assert settings.validate_hotkey("ctrl+shift+a") is True
    assert settings.validate_hotkey("a") is True
    assert settings.validate_hotkey("ctrl") is False  # modifier only
    assert settings.validate_hotkey("ctrl+shift") is False
    assert settings.validate_hotkey("") is False
    assert settings.validate_hotkey("+++") is False
    # Multi-char unknown keys should be rejected
    assert settings.validate_hotkey("notakey") is False
    assert settings.validate_hotkey("ctrl+notakey") is False
    # Known special keys should be accepted
    assert settings.validate_hotkey("ctrl+enter") is True
    assert settings.validate_hotkey("tab") is True
    # Punctuation single chars should be rejected (not resolvable by pynput)
    assert settings.validate_hotkey("ctrl+;") is False
    assert settings.validate_hotkey("/") is False
