"""Voice listener — wake-word detection and speech-to-text using VOSK.

Uses grammar-constrained VOSK for accurate command recognition (no garbage).
Mutes recognition while robot is speaking (prevents mic hearing speaker).
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


WAKE_VARIANTS = {
    "hello sonny", "hello sunny", "hello sony", "hello son",
    "hallo sonny", "hallo sunny", "halo sonny", "halo sunny",
    "hey sonny", "hey sunny", "hey sony",
    "hi sonny", "hi sunny", "hi sony",
}

WAKE_MAYBE = {"hello", "hallo", "halo", "hey", "hi"}

# Grammar: all words VOSK is allowed to recognize.
# This prevents it from hearing random sentences from background noise.
GRAMMAR = json.dumps([
    "hello", "hey", "hi", "halo", "hallo",
    "sonny", "sunny", "sony", "son",
    "follow", "the", "track", "line", "path",
    "go", "to", "qr", "code", "marker", "find",
    "stop", "halt", "freeze",
    "dance", "groove",
    "photo", "picture", "selfie", "take", "a",
    "come", "here", "me", "over",
    "patrol", "wander", "roam", "explore",
    "sleep", "rest", "standby",
    "search", "look", "around", "scan",
    "chat", "talk", "tell",
    "yes", "yeah", "yep", "sure", "okay", "ok",
    "no", "nope", "cancel", "never", "mind",
    "start", "begin", "please",
    "[unk]",
])


class VoiceListener:
    """Grammar-constrained VOSK listener with forgiving wake word."""

    SAMPLE_RATE = 16000
    CHUNK_SIZE = 4000

    def __init__(self, wake_phrase="hello sonny", model_path=None):
        self._model_path = model_path
        self._running = False
        self._callback = None
        self._thread = None
        self._speaker = None  # set via set_speaker() to mute during TTS

        self._lock = threading.Lock()
        self._awake = False
        self._wake_detected = False
        self._waiting_confirm = False
        self._last_text = ""
        self._muted_until = 0  # timestamp — ignore audio until this time

    @property
    def language(self):
        return "en"

    def set_speaker(self, speaker):
        """Link speaker so we can mute mic while robot talks."""
        self._speaker = speaker

    def start(self):
        if not _HAS_PYAUDIO or not _HAS_VOSK:
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
            logger.error("VOSK model not found!")
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

        rec = KaldiRecognizer(model, self.SAMPLE_RATE, GRAMMAR)
        logger.info("Voice ready. Say 'Hello Sonny' to wake up.")

        while self._running:
            try:
                data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                if not data:
                    continue

                # Skip if robot is currently speaking (prevent echo)
                if self._speaker and self._speaker.is_speaking:
                    self._muted_until = time.monotonic() + 1.0
                    continue
                if time.monotonic() < self._muted_until:
                    continue

                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").lower().strip()
                    if not text or text == "[unk]":
                        continue

                    # Filter out junk — must have at least one real word
                    real_words = [w for w in text.split() if w != "[unk]" and len(w) > 1]
                    if not real_words:
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
        words = set(text.split()) - {"[unk]", "the", "a", "to", "please"}

        # "stop" always works
        if words & {"stop", "halt", "freeze"}:
            if self._callback:
                self._callback("stop")
            return

        # Waiting for yes/no
        if self._waiting_confirm:
            with self._lock:
                self._waiting_confirm = False
            if words & {"yes", "yeah", "yep", "sure", "okay", "ok"}:
                self._do_wake(text)
            else:
                logger.info("Confirmation denied")
            return

        # Already awake — everything is a command
        if self._awake:
            if self._callback:
                self._callback(text)
            return

        # Not awake — check wake word
        for wake in WAKE_VARIANTS:
            if wake in text:
                after = text.split(wake, 1)[-1].strip()
                self._do_wake(after)
                return

        # Bare "hello" etc
        if words and words.issubset(WAKE_MAYBE | {"sonny", "sunny", "sony", "son"}):
            # Close enough — just wake up
            self._do_wake("")
            return

    def _do_wake(self, command_after=""):
        with self._lock:
            self._awake = True
            self._wake_detected = True
            self._waiting_confirm = False
        logger.info("AWAKE")
        if command_after and self._callback:
            self._callback(command_after)
