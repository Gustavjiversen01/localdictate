import subprocess
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMenu

from . import settings
from .engine import Engine
from .hotkey import HotkeyListener
from .ui import RecordingIndicator, SettingsDialog, TrayIcon


class Bridge(QObject):
    toggled = Signal(bool)
    transcription_done = Signal(str)
    error_occurred = Signal(str)


def _inject_text(text: str):
    if sys.platform == "linux":
        try:
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "3", "--", text],
                timeout=10,
            )
        except FileNotFoundError:
            from pynput.keyboard import Controller
            Controller().type(text)
    else:
        from pynput.keyboard import Controller
        Controller().type(text)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    cfg = settings.load()
    bridge = Bridge()
    engine = Engine(
        on_transcription=bridge.transcription_done.emit,
        on_error=bridge.error_occurred.emit,
    )

    # UI
    tray = TrayIcon()
    indicator = RecordingIndicator()

    menu = QMenu()
    settings_action = menu.addAction("Settings...")
    menu.addSeparator()
    quit_action = menu.addAction("Quit")
    tray.setContextMenu(menu)
    tray.show()

    # Settings dialog
    dialog_ref = [None]

    def open_settings():
        if dialog_ref[0] and dialog_ref[0].isVisible():
            dialog_ref[0].raise_()
            return
        dialog_ref[0] = SettingsDialog(settings.load(), on_settings_changed)
        dialog_ref[0].show()

    def on_settings_changed(new_cfg):
        nonlocal cfg
        cfg = new_cfg
        hotkey_listener.update_hotkey(cfg["hotkey"])
        tray.update_hotkey_tooltip(cfg["hotkey"])

    settings_action.triggered.connect(open_settings)
    quit_action.triggered.connect(app.quit)

    # Toggle callback (runs on pynput thread — emit signal only!)
    def on_hotkey_toggle(recording: bool):
        bridge.toggled.emit(recording)

    # Signal handlers (run on main thread — safe)
    def handle_toggle(recording: bool):
        if recording:
            tray.set_state(TrayIcon.RECORDING)
            indicator.show()
            engine.start_recording(device=cfg.get("audio_device"))
        else:
            indicator.hide()
            tray.set_state(TrayIcon.PROCESSING)
            engine.stop_and_transcribe(cfg["model"])

    def handle_transcription(text: str):
        tray.set_state(TrayIcon.IDLE)
        _inject_text(text)

    def handle_error(msg: str):
        tray.set_state(TrayIcon.IDLE)
        indicator.hide()
        tray.showMessage("OSW", msg, TrayIcon.MessageIcon.Warning, 3000)

    bridge.toggled.connect(handle_toggle)
    bridge.transcription_done.connect(handle_transcription)
    bridge.error_occurred.connect(handle_error)

    # Hotkey listener
    hotkey_listener = HotkeyListener(cfg["hotkey"], on_hotkey_toggle)
    hotkey_listener.start()

    # Onboarding
    if not cfg.get("onboarding_shown"):
        tray.showMessage(
            "OSW", f"Ready. Press {cfg['hotkey'].replace('+', ' + ').title()} to dictate.",
            TrayIcon.MessageIcon.Information, 4000,
        )
        cfg["onboarding_shown"] = True
        settings.save(cfg)

    # Initialize tooltip with current hotkey
    tray.update_hotkey_tooltip(cfg["hotkey"])

    # Quit handler — stop threads BEFORE Qt tears down
    def do_quit():
        hotkey_listener.stop()
        engine.cancel()
        engine.unload()
        app.quit()

    quit_action.triggered.disconnect()
    quit_action.triggered.connect(do_quit)

    app.exec()


if __name__ == "__main__":
    main()
