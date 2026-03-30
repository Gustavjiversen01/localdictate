import threading
from collections import deque

import numpy as np
import sounddevice as sd


class Engine:
    def __init__(self, on_transcription, on_error):
        self._on_transcription = on_transcription
        self._on_error = on_error
        self.model = None
        self._model_name = None
        self._chunks: deque[np.ndarray] = deque()
        self._stream = None
        self._recording = False

    def start_recording(self, device=None):
        self._chunks.clear()
        try:
            self._stream = sd.InputStream(
                samplerate=16000, channels=1, dtype="float32",
                device=device, callback=self._audio_callback,
            )
            self._stream.start()
            self._recording = True
        except Exception as e:
            self._on_error(f"Microphone error: {e}")

    def stop_and_transcribe(self, model_name: str):
        if not self._recording:
            return
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        chunks = list(self._chunks)
        self._chunks.clear()
        if not chunks:
            return

        audio = np.concatenate(chunks).flatten()
        duration = len(audio) / 16000
        if duration < 0.3:
            return

        thread = threading.Thread(
            target=self._transcribe, args=(audio, model_name), daemon=True
        )
        thread.start()

    def cancel(self):
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._chunks.clear()

    def _transcribe(self, audio: np.ndarray, model_name: str):
        try:
            self._ensure_model(model_name)
            segments, _ = self.model.transcribe(
                audio, language="en", beam_size=5, vad_filter=False,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            if text:
                self._on_transcription(text)
        except Exception as e:
            self._on_error(f"Transcription error: {e}")

    def _ensure_model(self, model_name: str):
        if self.model and self._model_name == model_name:
            return
        if self.model:
            del self.model
            import gc
            gc.collect()
        self.model = None
        self._model_name = model_name
        from faster_whisper import WhisperModel
        self.model = WhisperModel(
            model_name, device="cpu", compute_type="int8"
        )

    def _audio_callback(self, indata, frames, time_info, status):
        if self._recording:
            self._chunks.append(indata.copy())

    def unload(self):
        if self.model:
            del self.model
            import gc
            gc.collect()
        self.model = None
        self._model_name = None
