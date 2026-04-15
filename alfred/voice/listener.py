"""Voice listener — wake-word detection and speech-to-text using VOSK.

Design:
1. "Hello Sonny" / "hello sunny" / "hello sony" / etc all wake up
2. Just "hello" alone triggers "Are you talking to me?" confirmation
3. Once awake, stays awake — every sentence is a command
4. "stop" always works, even before wake
5. "sleep" puts back to sleep
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

try:
    from vosk import Model, KaldiRecognizer
    _HAS_VOSK = True
except ImportError:
    _HAS_VOSK = False


# All variations VOSK might hear when you say "Hello Sonny"
WAKE_EXACT = {
    "hello sonny", "hello sunny", "hello sony", "hello son",
    "hallo sonny", "hallo sunny", "halo sonny", "halo sunny",
    "hey sonny", "hey sunny", "hey sony",
    "hi sonny", "hi sunny", "hi sony",
}

# Partial wake — just "hello" or "hey" alone, needs confirmation
WAKE_MAYBE = {"hello", "hallo", "halo", "hey", "hi"}


class VoiceListener:
    """VOSK-based voice listener with forgiving wake word detection."""

    SAMPLE_RATE = 16000
    CHUNK_SIZE = 4000

    def __init__(self, wake_phrase="hello sonny", model_path=None):
        self._model_path = model_path
        self._running = False
        self._callback = None
        self._thread = None

        self._lock = threading.Lock()
        self._awake = False
        self._wake_detected = False
        self._waiting_confirm = False   # waiting for yes/no after "hello"
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

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

    def on_speech(self, callback):
        self._callback = callback

    def is_wake_word_detected(self):
        with self._lock:
            d = self._wake_detected
            self._wake_detected = False
        return d

    def put_to_sleep(self):
        with self._lock:
            self._awake = False
            self._waiting_confirm = False

    @property
    def last_text(self):
        with self._lock:
            return self._last_text

    @property
    def is_awake(self):
        with self._lock:
            return self._awake

    @property
    def is_waiting_confirm(self):
        with self._lock:
            return self._waiting_confirm

    def _find_model(self):
        if self._model_path and os.path.isdir(self._model_path):
            return self._model_path
        names = ["vosk-model-small-en-us-0.15", "vosk-model-en-us-0.22-lgraph"]
        dirs = [
            os.getcwd(),
            os.path.expanduser("~/AR-2"),
            os.path.expanduser("~/coursework/minilab6"),
            "/home/intc1002/coursework/minilab6",
            "/home/intc1002/AR-2",
            os.path.join(os.path.dirname(__file__), "..", ".."),
            os.path.expanduser("~"),
        ]
        for n in names:
            for d in dirs:
                p = os.path.join(d, n)
                if os.path.isdir(p) and len(os.listdir(p)) >= 2:
                    return p
        return None

    def _listen_loop(self):
        model_path = self._find_model()
        if not model_path:
            logger.error("VOSK model not found! Download vosk-model-small-en-us-0.15")
            return

        try:
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

        # Open recognition — no grammar constraint
        rec = KaldiRecognizer(model, self.SAMPLE_RATE)
        logger.info("Voice ready. Say 'Hello Sonny' to wake up.")

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

                    logger.info(f"[Voice] '{text}'")
                    self._process(text)

            except Exception as e:
                logger.error(f"Voice error: {e}")
                time.sleep(0.5)

        stream.stop_stream()
        stream.close()
        p.terminate()

    def _process(self, text):
        words = set(text.split())

        # "stop" always works
        if words & {"stop", "halt", "freeze"}:
            if self._callback:
                self._callback("stop")
            return

        # Waiting for yes/no confirmation after bare "hello"
        if self._waiting_confirm:
            with self._lock:
                self._waiting_confirm = False
            if words & {"yes", "yeah", "yep", "sure", "okay", "ok", "yea"}:
                self._do_wake(text)
            elif words & {"no", "nope", "nah", "cancel"}:
                logger.info("Not talking to Sonny, going back to sleep")
            else:
                # Ambiguous — treat as yes if awake context makes sense
                # but don't wake if they said something random
                logger.info(f"Unclear confirmation: '{text}', ignoring")
            return

        # Already awake — everything is a command
        if self._awake:
            if self._callback:
                self._callback(text)
            return

        # Not awake — check for wake word
        # Check exact matches first (hello sonny, hello sunny, etc)
        for wake in WAKE_EXACT:
            if wake in text:
                # Extract command after wake phrase if any
                after = text.split(wake, 1)[-1].strip()
                self._do_wake(after)
                return

        # Check partial wake — just "hello" alone
        stripped_words = words - {"[unk]", "the", "a", "to", "is", "it"}
        if stripped_words and stripped_words.issubset(WAKE_MAYBE):
            # They just said "hello" or "hey" — ask for confirmation
            with self._lock:
                self._waiting_confirm = True
            if self._callback:
                self._callback("__confirm_wake__")
            return

    def _do_wake(self, command_after=""):
        with self._lock:
            self._awake = True
            self._wake_detected = True
            self._waiting_confirm = False
        logger.info("AWAKE")
        if command_after and self._callback:
            self._callback(command_after)
