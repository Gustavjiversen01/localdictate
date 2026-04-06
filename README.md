![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)

<p align="center">
  <h1 align="center">LocalDictate</h1>
  <p align="center">Local voice-to-text, powered by Whisper.</p>
</p>

<p align="center">
  Press a shortcut. Speak. Press again. Text appears at your cursor.
</p>

---

I wanted something like Apple's dictation — but local, open, and on Linux. Every option I found was either cloud-dependent, paywalled, or abandoned. So I built it myself. No subscriptions, no telemetry, no profit motive. Just a tool that works. If that's what you're looking for too, this is for you.

---

**Local and private** — after a one-time model download from HuggingFace, all processing happens on your machine. No audio or text data is ever transmitted.

**Zero config** — launches into system tray, works immediately with your default microphone.

**Unobtrusive** — a small red dot appears while recording. That's it.

## Install

### Linux

```bash
sudo apt install portaudio19-dev xdotool
pip install git+https://github.com/Gustavjiversen01/localdictate.git
localdictate
```

Optional Wayland tools: `wtype` or `ydotool` for text injection on Wayland compositors.

### macOS (experimental, unverified)

```bash
brew install portaudio
pip install git+https://github.com/Gustavjiversen01/localdictate.git
localdictate
```

Note: macOS requires Accessibility permission for keyboard input.

### Windows (experimental, unverified)

```powershell
pip install git+https://github.com/Gustavjiversen01/localdictate.git
localdictate
```

That's it — `localdictate` installs as a command you can run from anywhere. It lives in your system tray.

## How it works

1. Press `Ctrl+Space` to start dictating
2. Speak naturally
3. Press `Ctrl+Space` to stop
4. Your words are typed into whatever app is focused

If direct text injection fails (e.g., missing `xdotool`), LocalDictate falls back to clipboard paste (Ctrl+V). This is best-effort: only text clipboard contents are preserved, and rich/image data may be lost.

Right-click the tray icon to open **Settings**, where you can configure:

| Setting | Options |
|---|---|
| **Quality** | Fast, Balanced (default), Quality, High, Maximum |
| **Microphone** | Any connected input device, or system default |
| **Shortcut** | Click Record, then press any key combination |
| **Launch at login** | Auto-start with your desktop |

## Models

Models are not included in the install — they download automatically from HuggingFace the first time you dictate. This is a **one-time download** (~800 MB for the default model). The tray icon will show "Downloading model..." while it downloads. After that, it's cached locally and loads in seconds.

> **Tip:** To avoid waiting on your first dictation, right-click the tray icon → Settings → click the **Download** button next to Quality. You can also pre-download other quality levels there.

| Label | Model | Size | Notes |
|---|---|---|---|
| Fast | [distil-small.en](https://huggingface.co/Systran/faster-distil-whisper-small.en) | ~336 MB | Ultra-fast, lowest latency |
| **Balanced** | [distil-medium.en](https://huggingface.co/Systran/faster-distil-whisper-medium.en) | **~800 MB** | **Default — best speed/quality tradeoff** |
| Quality | [distil-large-v3.5](https://huggingface.co/distil-whisper/distil-large-v3.5-ct2) | ~1.5 GB | High accuracy, trained on 4x more data |
| High | [turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) | ~1.6 GB | Near-maximum quality, much faster |
| Maximum | [large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) | ~3 GB | Best accuracy, slower |

Models are open-source — verify each model's license on its HuggingFace page.

Custom models: set `"model"` in `~/.config/localdictate/settings.json` to any [faster-whisper](https://github.com/SYSTRAN/faster-whisper) compatible model ID.

## Requirements

- Python 3.10+
- Linux (X11 primary; Wayland experimental — global hotkeys require X11, use tray menu on Wayland)
- macOS, Windows (experimental, unverified)
- PortAudio (`portaudio19-dev` on Debian/Ubuntu)

## Uninstall

```bash
pip uninstall localdictate
```

## Contributing

Bug reports and feature requests are welcome on the [issue tracker](https://github.com/Gustavjiversen01/localdictate/issues).

To set up a development environment:

```bash
git clone https://github.com/Gustavjiversen01/localdictate.git
cd localdictate
pip install -e ".[dev]"
pytest tests/
```

## License

[MIT](LICENSE)
