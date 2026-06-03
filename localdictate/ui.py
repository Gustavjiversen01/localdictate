import sys
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import settings
from .cache import is_model_cached


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
    """Small red dot. Repositions to the active monitor on each show."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(12, 12)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.85)

    def showEvent(self, event):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        geo = screen.geometry()
        self.move(geo.x() + geo.width() // 2 - 6, geo.y() + 6)
        super().showEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#e74c3c"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, 12, 12)
        p.end()


class TrayIcon(QSystemTrayIcon):
    IDLE, RECORDING, PROCESSING, DOWNLOADING = 0, 1, 2, 3

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
            self.IDLE: f"LocalDictate — {self._hotkey} to dictate",
            self.RECORDING: f"Recording... {self._hotkey} to stop",
            self.PROCESSING: "Transcribing...",
            self.DOWNLOADING: "Downloading model...",
        }
        self.setToolTip(tooltips.get(self._state, ""))

        if self._state == self.IDLE:
            self.setIcon(_make_icon("#e0e0e0", filled=False))
        elif self._state == self.RECORDING:
            self.setIcon(_make_icon("#e74c3c", filled=True, opacity=self._pulse_opacity))
        elif self._state == self.PROCESSING:
            self.setIcon(_make_icon("#e67e22", filled=True))
        elif self._state == self.DOWNLOADING:
            self.setIcon(_make_icon("#e67e22", filled=False))


class FallbackWindow(QWidget):
    """Minimal window for desktops without a system tray."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LocalDictate")
        self.setFixedSize(260, 80)
        layout = QVBoxLayout(self)
        self._status = QLabel("Idle")
        layout.addWidget(self._status)
        btn_row = QHBoxLayout()
        self._toggle_btn = QPushButton("Start Dictation")
        self._settings_btn = QPushButton("Settings")
        self._quit_btn = QPushButton("Quit")
        btn_row.addWidget(self._toggle_btn)
        btn_row.addWidget(self._settings_btn)
        btn_row.addWidget(self._quit_btn)
        layout.addLayout(btn_row)
        self._hotkey = "Ctrl+Space"

    def update_hotkey_tooltip(self, hotkey_str: str):
        self._hotkey = hotkey_str.replace("+", " + ").title()
        self.setWindowTitle(f"LocalDictate — {self._hotkey}")

    # Match TrayIcon constants so __main__.py can use either interchangeably
    IDLE, RECORDING, PROCESSING, DOWNLOADING = 0, 1, 2, 3
    MessageIcon = type("MI", (), {"Warning": 1, "Information": 0})()

    def set_state(self, state: int):
        labels = {
            self.IDLE: "Idle",
            self.RECORDING: "Recording...",
            self.PROCESSING: "Transcribing...",
            self.DOWNLOADING: "Downloading model...",
        }
        self._status.setText(labels.get(state, ""))
        if state == self.IDLE:
            self._toggle_btn.setText("Start Dictation")
        elif state == self.RECORDING:
            self._toggle_btn.setText("Stop Dictation")

    def showMessage(self, title, msg, icon=None, ms=3000):
        self._status.setText(msg)
        QTimer.singleShot(ms, lambda: self._status.setText("Idle"))


class SettingsDialog(QDialog):
    _download_finished = Signal(bool)

    _MODIFIERS = {"ctrl", "shift", "alt", "super"}
    _CANONICAL_ORDER = ["ctrl", "shift", "alt", "super"]

    def __init__(self, current_settings: dict, on_changed, parent=None):
        super().__init__(parent)
        self._settings = dict(current_settings)
        self._on_changed = on_changed
        self._download_finished.connect(self._on_download_finished)
        self.setWindowTitle("LocalDictate")
        self.setFixedSize(320, 270)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QFormLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Quality
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

        # Processing device (CPU / GPU). GPU needs an NVIDIA card + CUDA libs;
        # disable it when none is detected so users can't pick a path that fails.
        self._device = QComboBox()
        self._device.addItem("CPU", "cpu")
        self._device.addItem("GPU", "cuda")
        if not self._cuda_available():
            self._device.setItemText(1, "GPU (none detected)")
            gpu_item = self._device.model().item(1)
            if gpu_item is not None:
                gpu_item.setEnabled(False)
        # Map any stored value (incl. legacy "auto") to a concrete entry.
        want_gpu = self._settings.get("device") == "cuda" and self._cuda_available()
        self._device.setCurrentIndex(1 if want_gpu else 0)
        self._device.currentIndexChanged.connect(self._on_device_changed)
        layout.addRow("Processing", self._device)

        # Microphone
        self._mic = QComboBox()
        self._mic_devices = self._get_input_devices()
        self._mic.addItem("Default")
        for _idx, name in self._mic_devices:
            self._mic.addItem(name)
        current_dev = self._settings.get("audio_device")
        if current_dev is not None:
            for i, (idx, _name) in enumerate(self._mic_devices):
                if idx == current_dev:
                    self._mic.setCurrentIndex(i + 1)
                    break
        self._mic.currentIndexChanged.connect(self._on_mic_changed)
        layout.addRow("Microphone", self._mic)

        # Shortcut
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

        # Autostart
        self._autostart = QCheckBox()
        self._autostart.setChecked(self._settings.get("autostart", False))
        self._autostart.toggled.connect(self._on_autostart_changed)
        layout.addRow("Launch at login", self._autostart)

        # Hide autostart on unsupported platforms
        if sys.platform not in ("linux", "win32", "darwin"):
            self._autostart.setVisible(False)

    def _update_download_btn(self):
        model_id = settings.model_for_label(self._quality.currentText())
        if is_model_cached(model_id):
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

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import ctranslate2

            return ctranslate2.get_cuda_device_count() > 0
        except Exception:
            return False

    def _on_device_changed(self, _index: int):
        self._settings["device"] = self._device.currentData()
        self._save()

    def _on_mic_changed(self, index: int):
        if index == 0:
            self._settings["audio_device"] = None
        else:
            self._settings["audio_device"] = self._mic_devices[index - 1][0]
        self._save()

    # -- Shortcut recording with validation --

    def _start_recording_shortcut(self):
        self._capturing = True
        self._captured_keys = set()
        self._held_keys = set()
        self._prev_hotkey = self._settings["hotkey"]
        self._shortcut_label.setText("Press keys...")
        self._record_btn.setText("...")
        self._record_btn.setEnabled(False)

    def _stop_recording_shortcut(self):
        self._capturing = False
        self._record_btn.setText("Record")
        self._record_btn.setEnabled(True)

        if not self._captured_keys:
            self._shortcut_label.setText(self._prev_hotkey)
            return

        # Validate: must have at least one non-modifier key
        non_modifiers = self._captured_keys - self._MODIFIERS
        if not non_modifiers:
            self._shortcut_label.setText("Invalid shortcut")
            QTimer.singleShot(
                1500,
                lambda: self._shortcut_label.setText(self._prev_hotkey),
            )
            return

        # Canonical ordering: ctrl+shift+alt+super+<keys>
        mods = [m for m in self._CANONICAL_ORDER if m in self._captured_keys]
        keys = sorted(self._captured_keys - self._MODIFIERS)
        hotkey = "+".join(mods + keys)
        self._shortcut_label.setText(hotkey)
        self._settings["hotkey"] = hotkey
        self._save()

    def _on_autostart_changed(self, checked: bool):
        self._settings["autostart"] = checked
        from .autostart import set_autostart

        try:
            set_autostart(checked)
        except Exception:
            pass  # platform failure doesn't affect settings save
        self._save()

    def _save(self):
        settings.save(self._settings)
        self._on_changed(self._settings)

    _QT_KEY_NAMES = {
        Qt.Key_Control: "ctrl",
        Qt.Key_Shift: "shift",
        Qt.Key_Alt: "alt",
        Qt.Key_Meta: "super",
        Qt.Key_Space: "space",
        Qt.Key_Tab: "tab",
        Qt.Key_Return: "enter",
        Qt.Key_Escape: "esc",
    }

    def _key_name(self, qt_key: int) -> str | None:
        if qt_key in self._QT_KEY_NAMES:
            return self._QT_KEY_NAMES[qt_key]
        text = chr(qt_key).lower() if 0x20 < qt_key < 0x7F else None
        return text

    def keyPressEvent(self, event):
        if self._capturing:
            if event.isAutoRepeat():
                return
            name = self._key_name(event.key())
            if name:
                # Esc during capture → cancel
                if name == "esc":
                    self._capturing = False
                    self._record_btn.setText("Record")
                    self._record_btn.setEnabled(True)
                    self._shortcut_label.setText(self._prev_hotkey)
                    return
                self._captured_keys.add(name)
                self._held_keys.add(name)
                self._shortcut_label.setText(
                    "+".join(sorted(self._captured_keys)),
                )
            return
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_W and event.modifiers() & Qt.ControlModifier:
            self.close()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if self._capturing:
            if event.isAutoRepeat():
                return
            name = self._key_name(event.key())
            if name:
                self._held_keys.discard(name)
            # Finalize only when ALL keys are released
            if not self._held_keys:
                self._stop_recording_shortcut()
            return
        super().keyReleaseEvent(event)
