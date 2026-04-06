import os
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import settings
from .engine import Engine
from .hotkey import HotkeyListener
from .state import AppState
from .ui import FallbackWindow, RecordingIndicator, SettingsDialog, TrayIcon

_wayland = (
    os.environ.get("XDG_SESSION_TYPE") == "wayland"
    or "WAYLAND_DISPLAY" in os.environ
)


class Bridge(QObject):
    toggled = Signal()                        # hotkey or manual toggle
    transcription_done = Signal(int, str)     # job_id, text
    transcription_complete = Signal(int)       # job_id (no text)
    status_changed = Signal(int, str)          # job_id, message
    error_occurred = Signal(int, str)          # job_id, message
    engine_error = Signal(str)                 # non-job mic/startup errors
    clipboard_inject = Signal(str)
    injection_error = Signal(str)


# -- Text injection --

def _try_cmd(cmd, timeout=10):
    """Run a subprocess command. Returns True on success."""
    try:
        subprocess.run(cmd, timeout=timeout, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired):
        return False


_inject_lock = threading.Lock()


def _make_inject_text(bridge):
    """Create _inject_text closure with access to bridge signals."""

    def _inject_text(text: str):
        with _inject_lock:
            if sys.platform == "linux":
                if _wayland:
                    ok = (
                        _try_cmd(["wtype", "--", text])
                        or _try_cmd(["ydotool", "type", "--", text])
                    )
                else:
                    ok = _try_cmd([
                        "xdotool", "type", "--clearmodifiers",
                        "--delay", "3", "--", text,
                    ])
                if not ok:
                    bridge.clipboard_inject.emit(text)
                    return
            else:
                try:
                    from pynput.keyboard import Controller
                    Controller().type(text)
                except Exception:
                    bridge.clipboard_inject.emit(text)

    return _inject_text


# -- Clipboard fallback (best-effort, documented limitation) --

def _try_paste_cmd():
    """Simulate Ctrl+V per platform. Returns True on success."""
    if sys.platform == "linux":
        if _wayland:
            return _try_cmd(
                ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], timeout=2,
            )
        return _try_cmd(
            ["xdotool", "key", "--clearmodifiers", "ctrl+v"], timeout=2,
        )
    elif sys.platform == "darwin":
        return _try_cmd([
            "osascript", "-e",
            'tell application "System Events" to keystroke "v" using command down',
        ], timeout=2)
    elif sys.platform == "win32":
        try:
            from pynput.keyboard import Controller, Key
            k = Controller()
            k.press(Key.ctrl)
            k.press("v")
            k.release("v")
            k.release(Key.ctrl)
            return True
        except Exception:
            return False
    return False


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    cfg = settings.load()
    bridge = Bridge()

    # -- App state (owned here, not in Engine or HotkeyListener) --
    state = {"app": AppState.IDLE, "active_job": None, "shutting_down": False}

    # -- Clipboard queue (best-effort restore) --
    clipboard_queue = []
    clipboard_state = {"busy": False}

    def drain_clipboard():
        if not clipboard_queue:
            clipboard_state["busy"] = False
            return
        text = clipboard_queue.pop(0)
        old_text = QApplication.clipboard().text()
        QApplication.clipboard().setText(text)

        def do_paste():
            ok = _try_paste_cmd()
            if not ok and not state["shutting_down"]:
                bridge.injection_error.emit("Could not paste text.")
            # Schedule restore on the main thread AFTER paste completes
            if not state["shutting_down"]:
                QTimer.singleShot(0, restore)

        def restore():
            QApplication.clipboard().setText(old_text)
            # Small delay before processing next item to let paste settle
            QTimer.singleShot(100, drain_clipboard)

        threading.Thread(target=do_paste, daemon=True).start()

    def handle_clipboard_inject(text):
        if state["shutting_down"]:
            return
        clipboard_queue.append(text)
        if not clipboard_state["busy"]:
            clipboard_state["busy"] = True
            drain_clipboard()

    def handle_injection_error(msg):
        if state["shutting_down"]:
            return
        tray.showMessage(
            "LocalDictate", msg, TrayIcon.MessageIcon.Warning, 3000,
        )

    # -- Engine --
    engine = Engine(
        on_transcription=bridge.transcription_done.emit,
        on_complete=bridge.transcription_complete.emit,
        on_error=bridge.error_occurred.emit,
        on_engine_error=bridge.engine_error.emit,
        on_status=bridge.status_changed.emit,
    )

    _inject_text = _make_inject_text(bridge)

    # -- UI --
    indicator = RecordingIndicator()
    use_tray = QSystemTrayIcon.isSystemTrayAvailable()

    if use_tray:
        tray = TrayIcon()
        menu = QMenu()
        settings_action = menu.addAction("Settings...")
        menu.addSeparator()
        toggle_action = menu.addAction("Start Dictation")
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        tray.setContextMenu(menu)
        tray.show()
    else:
        fallback = FallbackWindow()
        tray = fallback  # same interface: set_state, update_hotkey_tooltip, showMessage
        settings_action = None
        toggle_action = None
        quit_action = None
        fallback._toggle_btn.clicked.connect(lambda: handle_toggle())
        fallback._settings_btn.clicked.connect(lambda: open_settings())
        fallback._quit_btn.clicked.connect(lambda: do_quit())
        fallback.show()

    # -- Settings dialog --
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

    if settings_action:
        settings_action.triggered.connect(open_settings)

    # -- Toggle (shared by hotkey and manual tray action) --
    def handle_toggle():
        if state["app"] == AppState.IDLE:
            state["active_job"] = None  # reject old callbacks
            ok = engine.start_recording(device=cfg.get("audio_device"))
            if ok:
                state["app"] = AppState.RECORDING
                tray.set_state(TrayIcon.RECORDING)
                indicator.show()
                if toggle_action:
                    toggle_action.setText("Stop Dictation")
            # mic error reported via engine_error (non-job-scoped)
        elif state["app"] == AppState.RECORDING:
            indicator.hide()
            queued, job_id = engine.stop_and_transcribe(
                cfg["model"],
                initial_prompt=cfg.get("initial_prompt"),
                length_penalty=cfg.get("length_penalty", 1.0),
                language=cfg.get("language"),
                device=cfg.get("device", "auto"),
                compute_type=cfg.get("compute_type", "default"),
            )
            if queued:
                state["active_job"] = job_id
                state["app"] = AppState.PROCESSING
                tray.set_state(TrayIcon.PROCESSING)
            else:
                state["app"] = AppState.IDLE
                tray.set_state(TrayIcon.IDLE)
            if toggle_action:
                toggle_action.setText("Start Dictation")

    def on_hotkey_triggered():
        bridge.toggled.emit()

    if toggle_action:
        toggle_action.triggered.connect(handle_toggle)

    # -- Job-scoped signal handlers --
    def handle_transcription(job_id: int, text: str):
        if state["shutting_down"] or job_id != state["active_job"]:
            return
        state["active_job"] = None
        state["app"] = AppState.IDLE
        tray.set_state(TrayIcon.IDLE)
        threading.Thread(
            target=_inject_text, args=(text,), daemon=True,
        ).start()

    def handle_complete(job_id: int):
        if state["shutting_down"] or job_id != state["active_job"]:
            return
        state["active_job"] = None
        state["app"] = AppState.IDLE
        tray.set_state(TrayIcon.IDLE)

    def handle_error(job_id: int, msg: str):
        if state["shutting_down"] or job_id != state["active_job"]:
            return
        state["active_job"] = None
        state["app"] = AppState.IDLE
        tray.set_state(TrayIcon.IDLE)
        indicator.hide()
        tray.showMessage(
            "LocalDictate", msg, TrayIcon.MessageIcon.Warning, 3000,
        )

    def handle_status(job_id: int, msg: str):
        if state["shutting_down"] or job_id != state["active_job"]:
            return
        if msg:
            state["app"] = AppState.DOWNLOADING
            tray.set_state(TrayIcon.DOWNLOADING)
        else:
            state["app"] = AppState.PROCESSING
            tray.set_state(TrayIcon.PROCESSING)

    def handle_engine_error(msg: str):
        if state["shutting_down"]:
            return
        state["app"] = AppState.IDLE
        tray.set_state(TrayIcon.IDLE)
        indicator.hide()
        if toggle_action:
            toggle_action.setText("Start Dictation")
        tray.showMessage(
            "LocalDictate", msg, TrayIcon.MessageIcon.Warning, 3000,
        )

    # -- Connect signals --
    bridge.toggled.connect(handle_toggle)
    bridge.transcription_done.connect(handle_transcription)
    bridge.transcription_complete.connect(handle_complete)
    bridge.error_occurred.connect(handle_error)
    bridge.status_changed.connect(handle_status)
    bridge.engine_error.connect(handle_engine_error)
    bridge.clipboard_inject.connect(handle_clipboard_inject)
    bridge.injection_error.connect(handle_injection_error)

    # -- Hotkey listener --
    hotkey_listener = HotkeyListener(cfg["hotkey"], on_hotkey_triggered)
    hotkey_ok = hotkey_listener.start()

    if not hotkey_ok and _wayland:
        tray.showMessage(
            "LocalDictate",
            "Wayland detected. Global hotkeys may not work. "
            "Use the tray menu to start/stop dictation.",
            TrayIcon.MessageIcon.Warning, 5000,
        )
    elif not hotkey_ok:
        tray.showMessage(
            "LocalDictate",
            "Could not start hotkey listener. "
            "Use the tray menu to start/stop dictation.",
            TrayIcon.MessageIcon.Warning, 5000,
        )

    # -- Startup migration: clean up stale osw autostart --
    from .autostart import cleanup_stale_osw, set_autostart
    cleanup_stale_osw()
    if cfg.get("autostart"):
        try:
            set_autostart(True)
        except Exception:
            pass

    # -- Onboarding --
    if not cfg.get("onboarding_shown"):
        hotkey_display = cfg["hotkey"].replace("+", " + ").title()
        tray.showMessage(
            "LocalDictate",
            f"Ready. Press {hotkey_display} to dictate.\n"
            "First use will download the speech model (~800 MB).",
            TrayIcon.MessageIcon.Information, 5000,
        )
        cfg["onboarding_shown"] = True
        settings.save(cfg)

    tray.update_hotkey_tooltip(cfg["hotkey"])

    # -- Quit handler --
    def do_quit():
        state["shutting_down"] = True

        # Run teardown in a background thread to avoid freezing the UI.
        # Daemon=True ensures process exit even if cleanup hangs.
        def _teardown():
            hotkey_listener.stop()
            engine.cancel()
            engine.unload()

        t = threading.Thread(target=_teardown, daemon=True)
        t.start()
        # Give teardown a short window, then quit regardless
        QTimer.singleShot(500, app.quit)

    if quit_action:
        quit_action.triggered.connect(do_quit)

    app.exec()


if __name__ == "__main__":
    main()
