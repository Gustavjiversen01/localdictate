import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QGraphicsOpacityEffect,
    QHBoxLayout, QLineEdit, QPushButton, QSystemTrayIcon, QWidget,
)

from . import settings


def _make_icon(color: str, filled: bool = False, opacity: float = 1.0) -> QIcon:
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setOpacity(opacity)
    cx, cy = size // 2, size // 2

    if filled:
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - 24, cy - 24, 48, 48)
    else:
        pen = QPen(QColor(color), 4)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(cx - 10, cy - 20, 20, 28, 7, 7)
        p.drawArc(cx - 16, cy - 6, 32, 28, 0, -180 * 16)
        p.drawLine(cx, cy + 8, cx, cy + 18)
        p.drawLine(cx - 8, cy + 18, cx + 8, cy + 18)

    p.end()
    return QIcon(pm)


class RecordingIndicator(QWidget):
    """Small red dot at top-center of screen. Visible only while recording."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.Tool | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(12, 12)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.85)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() // 2 - 6, 6)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#e74c3c"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, 12, 12)
        p.end()


class TrayIcon(QSystemTrayIcon):
    IDLE, RECORDING, PROCESSING = range(3)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = self.IDLE
        self._hotkey = "Ctrl+Space"
        self._pulse_timer = QTimer()
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_opacity = 1.0
        self._pulse_dir = -1
        self._update_icon()

    def update_hotkey_tooltip(self, hotkey_str: str):
        self._hotkey = hotkey_str.replace("+", " + ").title()
        self._update_icon()

    def set_state(self, state: int):
        self._state = state
        if state == self.RECORDING:
            self._pulse_opacity = 1.0
            self._pulse_timer.start(66)
        else:
            self._pulse_timer.stop()
        self._update_icon()

    def _pulse_tick(self):
        self._pulse_opacity += self._pulse_dir * 0.08
        if self._pulse_opacity <= 0.3:
            self._pulse_dir = 1
        elif self._pulse_opacity >= 1.0:
            self._pulse_dir = -1
        self._update_icon()

    def _update_icon(self):
        tooltips = {
            self.IDLE: f"OSW — {self._hotkey} to dictate",
            self.RECORDING: f"Recording... {self._hotkey} to stop",
            self.PROCESSING: "Transcribing...",
        }
        self.setToolTip(tooltips.get(self._state, ""))

        if self._state == self.IDLE:
            self.setIcon(_make_icon("#e0e0e0", filled=False))
        elif self._state == self.RECORDING:
            self.setIcon(_make_icon("#e74c3c", filled=True, opacity=self._pulse_opacity))
        elif self._state == self.PROCESSING:
            self.setIcon(_make_icon("#e67e22", filled=True))


class SettingsDialog(QDialog):
    _download_finished = Signal(bool)  # True = success, False = failure

    def __init__(self, current_settings: dict, on_changed, parent=None):
        super().__init__(parent)
        self._settings = dict(current_settings)
        self._on_changed = on_changed
        self._download_finished.connect(self._on_download_finished)
        self.setWindowTitle("OSW")
        self.setFixedSize(320, 230)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QFormLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        quality_row = QWidget()
        quality_layout = QHBoxLayout(quality_row)
        quality_layout.setContentsMargins(0, 0, 0, 0)
        quality_layout.setSpacing(6)
        self._quality = QComboBox()
        labels = list(settings.MODELS.keys())
        self._quality.addItems(labels)
        current_label = settings.label_for_model(self._settings["model"])
        if current_label in labels:
            self._quality.setCurrentText(current_label)
        self._quality.currentTextChanged.connect(self._on_quality_changed)
        quality_layout.addWidget(self._quality)
        self._download_btn = QPushButton("Download")
        self._download_btn.setFixedWidth(72)
        self._download_btn.clicked.connect(self._download_model)
        quality_layout.addWidget(self._download_btn)
        layout.addRow("Quality", quality_row)
        self._update_download_btn()

        self._mic = QComboBox()
        self._mic_devices = self._get_input_devices()
        self._mic.addItem("Default")
        for idx, name in self._mic_devices:
            self._mic.addItem(name)
        current_dev = self._settings.get("audio_device")
        if current_dev is not None:
            for i, (idx, name) in enumerate(self._mic_devices):
                if idx == current_dev:
                    self._mic.setCurrentIndex(i + 1)
                    break
        self._mic.currentIndexChanged.connect(self._on_mic_changed)
        layout.addRow("Microphone", self._mic)

        shortcut_row = QWidget()
        shortcut_layout = QHBoxLayout(shortcut_row)
        shortcut_layout.setContentsMargins(0, 0, 0, 0)
        shortcut_layout.setSpacing(6)
        self._shortcut_label = QLineEdit(self._settings["hotkey"])
        self._shortcut_label.setReadOnly(True)
        self._record_btn = QPushButton("Record")
        self._record_btn.setFixedWidth(60)
        self._record_btn.clicked.connect(self._start_recording_shortcut)
        shortcut_layout.addWidget(self._shortcut_label)
        shortcut_layout.addWidget(self._record_btn)
        layout.addRow("Shortcut", shortcut_row)
        self._capturing = False

        self._autostart = QCheckBox()
        self._autostart.setChecked(self._settings.get("autostart", False))
        self._autostart.toggled.connect(self._on_autostart_changed)
        layout.addRow("Launch at login", self._autostart)

    @staticmethod
    def _is_model_cached(model_id: str) -> bool:
        from faster_whisper.utils import _MODELS
        from huggingface_hub import scan_cache_dir
        repo_id = _MODELS.get(model_id, model_id)
        try:
            cache = scan_cache_dir()
            return any(r.repo_id == repo_id for r in cache.repos)
        except Exception:
            return False

    def _update_download_btn(self):
        model_id = settings.model_for_label(self._quality.currentText())
        if self._is_model_cached(model_id):
            self._download_btn.hide()
        else:
            self._download_btn.show()
            self._download_btn.setText("Download")
            self._download_btn.setEnabled(True)

    def _download_model(self):
        model_id = settings.model_for_label(self._quality.currentText())
        self._download_btn.setText("...")
        self._download_btn.setEnabled(False)

        def do_download():
            try:
                from faster_whisper.utils import download_model
                download_model(model_id)
                self._download_finished.emit(True)
            except Exception:
                self._download_finished.emit(False)

        threading.Thread(target=do_download, daemon=True).start()

    def _on_download_finished(self, success: bool):
        if success:
            self._download_btn.hide()
        else:
            self._download_btn.setText("Retry")
            self._download_btn.setEnabled(True)

    @staticmethod
    def _get_input_devices() -> list[tuple[int, str]]:
        import sounddevice as sd
        devices = sd.query_devices()
        return [
            (i, d["name"])
            for i, d in enumerate(devices)
            if d["max_input_channels"] > 0 and d["name"] not in ("default", "pipewire", "pulse")
        ]

    def _on_quality_changed(self, label: str):
        self._settings["model"] = settings.model_for_label(label)
        self._save()
        self._update_download_btn()

    def _on_mic_changed(self, index: int):
        if index == 0:
            self._settings["audio_device"] = None
        else:
            self._settings["audio_device"] = self._mic_devices[index - 1][0]
        self._save()

    def _start_recording_shortcut(self):
        self._capturing = True
        self._captured_keys = set()
        self._shortcut_label.setText("Press keys...")
        self._record_btn.setText("...")
        self._record_btn.setEnabled(False)

    def _stop_recording_shortcut(self):
        self._capturing = False
        self._record_btn.setText("Record")
        self._record_btn.setEnabled(True)
        if self._captured_keys:
            hotkey = "+".join(sorted(self._captured_keys))
            self._shortcut_label.setText(hotkey)
            self._settings["hotkey"] = hotkey
            self._save()

    def _on_autostart_changed(self, checked: bool):
        self._settings["autostart"] = checked
        self._apply_autostart(checked)
        self._save()

    def _save(self):
        settings.save(self._settings)
        self._on_changed(self._settings)

    def _apply_autostart(self, enabled: bool):
        if sys.platform != "linux":
            return
        autostart_dir = Path.home() / ".config" / "autostart"
        desktop_file = autostart_dir / "osw.desktop"
        if enabled:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            desktop_file.write_text(
                "[Desktop Entry]\nType=Application\nName=OSW\n"
                f"Exec={sys.executable} -m osw\nHidden=false\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
        elif desktop_file.exists():
            desktop_file.unlink()

    _QT_KEY_NAMES = {
        Qt.Key_Control: "ctrl", Qt.Key_Shift: "shift", Qt.Key_Alt: "alt",
        Qt.Key_Meta: "super", Qt.Key_Space: "space", Qt.Key_Tab: "tab",
        Qt.Key_Return: "enter", Qt.Key_Escape: "esc",
    }

    def _key_name(self, qt_key: int) -> str | None:
        if qt_key in self._QT_KEY_NAMES:
            return self._QT_KEY_NAMES[qt_key]
        text = chr(qt_key).lower() if 0x20 < qt_key < 0x7F else None
        return text

    def keyPressEvent(self, event):
        if self._capturing:
            name = self._key_name(event.key())
            if name:
                self._captured_keys.add(name)
                self._shortcut_label.setText("+".join(sorted(self._captured_keys)))
            return
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_W and event.modifiers() & Qt.ControlModifier:
            self.close()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if self._capturing:
            self._stop_recording_shortcut()
            return
        super().keyReleaseEvent(event)
