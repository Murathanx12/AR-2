"""Voice listener — wake-word detection and speech-to-text using VOSK.

Uses VOSK (offline) + PyAudio for lightweight, low-latency voice recognition.
Based on the proven minilab6.py approach.
"""

import threading
import time
import logging
import json
import os

logger = logging.getLogger(__name__)

try:
    import pyaudio
    _HAS_PYAUDIO = True
except (ImportError, OSError):
    _HAS_PYAUDIO = False
    logger.warning("pyaudio not available — voice listener disabled")

try:
    from vosk import Model, KaldiRecognizer
    _HAS_VOSK = True
except ImportError:
    _HAS_VOSK = False
    logger.warning("vosk not available — voice listener disabled")


class VoiceListener:
    """Listens for wake word and task commands using VOSK offline STT.

    Grammar-constrained recognition for fast, accurate command detection.
    When hardware is unavailable, all methods are safe no-ops.
    """

    SAMPLE_RATE = 16000
    CHUNK_SIZE = 4000  # ~250ms chunks at 16kHz

    # VOSK grammar — all words the recognizer will try to match
    GRAMMAR = json.dumps([
        # Wake phrase
        "hello", "sonny", "hello sonny",
        # Task commands (R1)
        "follow", "track", "follow track", "follow the track",
        "go", "to", "code", "qr", "qr code", "go to qr code",
        "go to code", "go to marker",
        # Control commands
        "stop", "halt", "freeze",
        "dance", "groove",
        "photo", "picture", "selfie",
        "come", "here", "come here",
        "patrol", "wander", "roam",
        "sleep", "rest", "standby",
        "search",
        # Conversation (EC3)
        "chat", "talk", "tell me",
        # Confirmation
        "confirm", "ok", "okay", "yes", "cancel", "no",
        # Filler
        "[unk]",
    ])

    def __init__(self, wake_phrase="Hello Sonny",
                 model_path=None):
        """
        Args:
            wake_phrase: Phrase to activate command listening.
            model_path: Path to VOSK model directory. Auto-detected if None.
        """
        self._wake_phrase = wake_phrase.lower()
        self._model_path = model_path
        self._running = False
        self._callback = None
        self._thread = None

        # Thread-safe event flags (like minilab6.py pattern)
        self._lock = threading.Lock()
        self._wake_detected = False
        self._listening_for_command = False
        self._last_text = ""

    def start(self):
        """Start background listening thread."""
        if not _HAS_PYAUDIO or not _HAS_VOSK:
            logger.warning("Cannot start voice listener: pyaudio/vosk not available")
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("Voice listener started (VOSK)")

    def stop(self):
        """Stop listening."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Voice listener stopped")

    def on_speech(self, callback):
        """Register callback for recognised speech: callback(text).

        The callback receives the command text (after wake phrase detection).
        """
        self._callback = callback

    def is_wake_word_detected(self):
        """Whether the wake word was detected in recent audio. Consuming."""
        with self._lock:
            detected = self._wake_detected
            self._wake_detected = False
        return detected

    @property
    def last_text(self):
        """Last recognised text (for debug display)."""
        with self._lock:
            return self._last_text

    def _find_model(self):
        """Find VOSK model directory."""
        if self._model_path and os.path.isdir(self._model_path):
            return self._model_path

        # Common locations on Pi
        candidates = [
            os.path.join(os.getcwd(), "vosk-model-small-en-us-0.15"),
            os.path.expanduser("~/coursework/minilab6/vosk-model-small-en-us-0.15"),
            "/home/intc1002/coursework/minilab6/vosk-model-small-en-us-0.15",
            os.path.join(os.path.dirname(__file__), "..", "..", "vosk-model-small-en-us-0.15"),
        ]
        for path in candidates:
            if os.path.isdir(path):
                return path
        return None

    def _listen_loop(self):
        """Background loop: stream audio to VOSK, detect wake word + commands."""
        model_path = self._find_model()
        if not model_path:
            logger.error("VOSK model not found. Voice listener disabled.")
            logger.error("Download: https://alphacephei.com/vosk/models -> vosk-model-small-en-us-0.15")
            return

        try:
            logger.info(f"Loading VOSK model from {model_path}...")
            model = Model(model_path)
            logger.info("VOSK model loaded.")
        except Exception as e:
            logger.error(f"Failed to load VOSK model: {e}")
            return

        p = pyaudio.PyAudio()
        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.SAMPLE_RATE,
                input=True,
                frames_per_buffer=self.CHUNK_SIZE,
            )
        except Exception as e:
            logger.error(f"Failed to open audio input: {e}")
            p.terminate()
            return

        rec = KaldiRecognizer(model, self.SAMPLE_RATE, self.GRAMMAR)
        logger.info(f"Voice listener ready. Wake phrase: '{self._wake_phrase}'")

        while self._running:
            try:
                data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                if len(data) == 0:
                    continue

                if rec.AcceptWaveform(data):
                    result = rec.Result()
                    try:
                        r = json.loads(result)
                        text = r.get("text", "").lower().strip()
                        if not text:
                            continue

                        with self._lock:
                            self._last_text = text

                        logger.debug(f"[Voice] Heard: {text}")
                        self._process_text(text)

                    except json.JSONDecodeError:
                        continue

            except Exception as e:
                logger.error(f"Voice listener error: {e}")
                time.sleep(0.5)

        # Cleanup
        stream.stop_stream()
        stream.close()
        p.terminate()

    def _process_text(self, text):
        """Process recognised text: check for wake word, dispatch commands."""
        wake = self._wake_phrase

        if wake in text:
            with self._lock:
                self._wake_detected = True
                self._listening_for_command = True
            logger.info("Wake word detected!")

            # Extract command after wake phrase (if any)
            idx = text.find(wake)
            command = text[idx + len(wake):].strip()
            if command and self._callback:
                self._callback(command)
                with self._lock:
                    self._listening_for_command = False

        elif self._listening_for_command:
            # Already woke up, now listening for the command
            if self._callback:
                self._callback(text)
            with self._lock:
                self._listening_for_command = False
