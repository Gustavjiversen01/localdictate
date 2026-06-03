import json
from pathlib import Path

from platformdirs import user_config_dir

MODELS = {
    "Fast": "distil-small.en",
    "Balanced": "distil-medium.en",
    "Quality": "distil-large-v3.5",
    "High": "turbo",
    "Maximum": "large-v3",
}

MODEL_REPOS = {
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
    "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
    "distil-large-v3.5": "distil-whisper/distil-large-v3.5-ct2",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
}

ENGLISH_ONLY_MODELS = {"distil-small.en", "distil-medium.en", "distil-large-v3.5"}

_KNOWN_MODIFIERS = {"ctrl", "shift", "alt", "super"}

DEFAULTS = {
    "model": "distil-medium.en",
    "hotkey": "ctrl+space",
    "audio_device": None,  # None = system default
    "autostart": False,
    "onboarding_shown": False,
    "initial_prompt": None,  # condition Whisper (e.g. "no filler words")
    "length_penalty": 1.0,  # >1 penalises long sequences / filler words
    "language": None,  # None = auto-detect (English-only models default to "en")
    "device": "cpu",  # "cpu", "cuda", or "auto"; CPU is the safe cross-machine default
    "compute_type": "default",  # "default", "int8", "float16", etc.
}

_config_dir = Path(user_config_dir("localdictate"))
_config_file = _config_dir / "settings.json"
_old_config_file = Path(user_config_dir("osw")) / "settings.json"


def load() -> dict:
    # Migrate from old osw config if new config doesn't exist yet
    if not _config_file.exists() and _old_config_file.exists():
        try:
            with open(_old_config_file) as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                migrated = {**DEFAULTS, **stored}
                if not validate_hotkey(migrated.get("hotkey", "")):
                    migrated["hotkey"] = DEFAULTS["hotkey"]
                save(migrated)
                return migrated
        except (json.JSONDecodeError, ValueError, OSError):
            pass  # corrupt old config — start fresh

    if _config_file.exists():
        try:
            with open(_config_file) as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                cfg = {**DEFAULTS, **stored}
                if not validate_hotkey(cfg.get("hotkey", "")):
                    cfg["hotkey"] = DEFAULTS["hotkey"]
                return cfg
        except (json.JSONDecodeError, ValueError, OSError):
            pass  # corrupt config — fall back to defaults
    return dict(DEFAULTS)


def save(settings: dict):
    import os
    import sys
    import tempfile

    _config_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_config_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(settings, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _config_file)
        # Best-effort directory fsync for power-loss durability (POSIX only)
        if sys.platform != "win32":
            try:
                dirfd = os.open(str(_config_dir), os.O_RDONLY)
                try:
                    os.fsync(dirfd)
                finally:
                    os.close(dirfd)
            except OSError:
                pass
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_KNOWN_KEYS = {
    "space",
    "tab",
    "enter",
    "esc",
}


def validate_hotkey(hotkey_str: str) -> bool:
    """Validate hotkey string: non-empty, known keys, at least one non-modifier."""
    parts = {k.strip().lower() for k in hotkey_str.split("+") if k.strip()}
    if not parts:
        return False
    # Every part must be a known modifier, a known special key, or a single alnum char
    for p in parts:
        if p in _KNOWN_MODIFIERS or p in _KNOWN_KEYS:
            continue
        if len(p) == 1 and p.isalnum():
            continue
        return False
    non_modifiers = parts - _KNOWN_MODIFIERS
    return len(non_modifiers) >= 1


def label_for_model(model_id: str) -> str:
    for label, mid in MODELS.items():
        if mid == model_id:
            return label
    return model_id


def model_for_label(label: str) -> str:
    return MODELS.get(label, label)
