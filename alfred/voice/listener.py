"""Voice listener — wake-word detection and speech-to-text using VOSK.

Simple design:
1. Say "Hello Sonny" once to wake up
2. Robot stays awake — every sentence after that is treated as a command
3. Say "stop" at any time to stop
4. Say "sleep" or "go to sleep" to put back in sleep mode (requires wake again)

Uses open VOSK recognition (no grammar constraint) for maximum flexibility.
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
    """Listens for wake word and commands using VOSK offline STT.

    After wake word is detected once, stays awake and treats every
    recognized sentence as a command. No need to say wake word again.
    """

    SAMPLE_RATE = 16000
    CHUNK_SIZE = 4000  # ~250ms at 16kHz

    def __init__(self, wake_phrase="hello sonny", model_path=None):
        self._wake_phrase = wake_phrase.lower().strip()
        self._model_path = model_path
        self._running = False
        self._callback = None
        self._thread = None

        self._lock = threading.Lock()
        self._awake = False          # True after wake word heard
        self._wake_detected = False  # consumed by FSM on first wake
        self._last_text = ""

    @property
    def language(self):
        return "en"

    def start(self):
        if not _HAS_PYAUDIO or not _HAS_VOSK:
            logger.warning("Cannot start voice listener: missing pyaudio/vosk")
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("Voice listener started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

    def on_speech(self, callback):
        """Register callback: callback(text) called for every command."""
        self._callback = callback

    def is_wake_word_detected(self):
        """Check and consume wake word flag (for FSM IDLE->LISTENING)."""
        with self._lock:
            detected = self._wake_detected
            self._wake_detected = False
        return detected

    def put_to_sleep(self):
        """Put listener back to sleep — requires wake word again."""
        with self._lock:
            self._awake = False
        logger.info("Voice listener sleeping — say wake phrase to wake")

    @property
    def last_text(self):
        with self._lock:
            return self._last_text

    def _find_model(self):
        """Find VOSK model directory."""
        if self._model_path and os.path.isdir(self._model_path):
            return self._model_path

        model_names = [
            "vosk-model-small-en-us-0.15",
            "vosk-model-en-us-0.22-lgraph",
        ]
        search_dirs = [
            os.getcwd(),
            os.path.expanduser("~/AR-2"),
            os.path.expanduser("~/coursework/minilab6"),
            "/home/intc1002/coursework/minilab6",
            "/home/intc1002/AR-2",
            os.path.join(os.path.dirname(__file__), "..", ".."),
            os.path.expanduser("~"),
        ]
        for name in model_names:
            for d in search_dirs:
                path = os.path.join(d, name)
                if os.path.isdir(path) and len(os.listdir(path)) >= 2:
                    return path
        return None

    def _listen_loop(self):
        model_path = self._find_model()
        if not model_path:
            logger.error("VOSK model not found! Download vosk-model-small-en-us-0.15")
            return

        try:
            logger.info(f"Loading VOSK model from {model_path}")
            model = Model(model_path)
        except Exception as e:
            logger.error(f"Failed to load VOSK model: {e}")
            return

        p = pyaudio.PyAudio()
        try:
            stream = p.open(
                format=pyaudio.paInt16, channels=1,
                rate=self.SAMPLE_RATE, input=True,
                frames_per_buffer=self.CHUNK_SIZE,
            )
        except Exception as e:
            logger.error(f"Failed to open audio: {e}")
            p.terminate()
            return

        # Open recognition — no grammar constraint for maximum flexibility
        rec = KaldiRecognizer(model, self.SAMPLE_RATE)
        logger.info(f"Voice ready. Say '{self._wake_phrase}' to wake up.")

        while self._running:
            try:
                data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                if not data:
                    continue

                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").lower().strip()
                    if not text:
                        continue

                    with self._lock:
                        self._last_text = text

                    logger.info(f"[Voice] Heard: '{text}'")

                    # "stop" always works, even before wake
                    if self._is_stop_command(text):
                        if self._callback:
                            self._callback("stop")
                        continue

                    # Check for wake phrase
                    if not self._awake:
                        if self._wake_phrase in text:
                            with self._lock:
                                self._awake = True
                                self._wake_detected = True
                            logger.info("AWAKE — now listening for commands")
                            # Check if command was said in same sentence
                            after = text.split(self._wake_phrase, 1)[-1].strip()
                            if after and self._callback:
                                self._callback(after)
                    else:
                        # Already awake — everything is a command
                        if self._callback:
                            self._callback(text)

            except Exception as e:
                logger.error(f"Voice error: {e}")
                time.sleep(0.5)

        stream.stop_stream()
        stream.close()
        p.terminate()

    @staticmethod
    def _is_stop_command(text):
        """Check if text is a stop command — works even before wake."""
        stop_words = {"stop", "halt", "freeze"}
        words = set(text.split())
        return bool(words & stop_words)
