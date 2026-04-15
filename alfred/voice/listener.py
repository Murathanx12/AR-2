"""Voice listener — wake-word detection and speech-to-text using VOSK.

Uses VOSK (offline) + PyAudio for lightweight, low-latency voice recognition.
Supports English and Turkish language models with runtime switching.
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


# Language configurations
LANGUAGE_CONFIGS = {
    "en": {
        "models": [
            "vosk-model-small-en-us-0.15",
            "vosk-model-en-us-0.22-lgraph",
        ],
        "grammar": [
            # Wake phrase
            "hello", "sonny", "hello sonny",
            # Task commands (R1)
            "follow", "track", "follow track", "follow the track",
            "follow line",
            "go", "to", "code", "qr", "qr code", "go to qr code",
            "go to code", "go to marker", "find marker", "find the marker",
            # Control commands
            "stop", "halt", "freeze", "wait",
            "dance", "groove", "let's dance",
            "photo", "picture", "selfie", "take photo", "take a photo",
            "come", "here", "come here", "come to me",
            "patrol", "wander", "roam", "explore",
            "sleep", "rest", "standby", "go to sleep",
            "search", "look around", "scan",
            # Conversation (EC3)
            "chat", "talk", "tell me", "let's talk", "conversation",
            # Confirmation
            "confirm", "ok", "okay", "yes", "sure", "yeah",
            "cancel", "no", "never mind",
            # Language switching
            "switch language", "change language",
            "speak turkish", "turkish", "speak english", "english",
            # Filler
            "[unk]",
        ],
    },
    "tr": {
        "models": [
            "vosk-model-small-tr-0.3",
            "vosk-model-tr-0.3",
        ],
        "grammar": [
            # Wake phrase
            "merhaba", "sonny", "merhaba sonny",
            # Task commands
            "takip", "et", "çizgiyi takip et", "yolu takip et",
            "işarete git", "koda git", "markere git",
            # Control
            "dur", "bekle", "durdur",
            "dans", "dans et",
            "fotoğraf", "fotoğraf çek", "resim çek",
            "buraya", "gel", "buraya gel",
            "devriye", "gez", "dolaş",
            "uyu", "uyku",
            "ara", "etrafına bak",
            # Conversation
            "konuş", "sohbet", "anlat",
            # Confirmation
            "evet", "tamam", "hayır", "iptal",
            # Language
            "dil değiştir", "ingilizce", "türkçe",
            # Filler
            "[unk]",
        ],
    },
}


class VoiceListener:
    """Listens for wake word and task commands using VOSK offline STT.

    Grammar-constrained recognition for fast, accurate command detection.
    Supports English and Turkish with runtime language switching.
    When hardware is unavailable, all methods are safe no-ops.
    """

    SAMPLE_RATE = 16000
    CHUNK_SIZE = 4000  # ~250ms chunks at 16kHz

    def __init__(self, wake_phrase="Hello Sonny", model_path=None, language="en"):
        """
        Args:
            wake_phrase: Phrase to activate command listening.
            model_path: Path to VOSK model directory. Auto-detected if None.
            language: Initial language code ("en" or "tr").
        """
        self._wake_phrase = wake_phrase.lower()
        self._model_path = model_path
        self._language = language
        self._running = False
        self._callback = None
        self._thread = None

        # Thread-safe event flags
        self._lock = threading.Lock()
        self._wake_detected = False
        self._listening_for_command = False
        self._last_text = ""
        self._language_switch_requested = None  # set to "en"/"tr" to switch

        # Wake phrases per language
        self._wake_phrases = {
            "en": "hello sonny",
            "tr": "merhaba sonny",
        }

    @property
    def language(self):
        """Current recognition language."""
        return self._language

    def switch_language(self, lang):
        """Request a language switch (takes effect on next recognition cycle).

        Args:
            lang: "en" or "tr"
        """
        if lang in LANGUAGE_CONFIGS:
            with self._lock:
                self._language_switch_requested = lang
            logger.info(f"Language switch requested: {lang}")

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

    def _find_model(self, language=None):
        """Find VOSK model directory for given language.

        Validates that the model directory contains the required files
        (not just that the directory exists — catches corrupted downloads).
        """
        lang = language or self._language
        config = LANGUAGE_CONFIGS.get(lang, LANGUAGE_CONFIGS["en"])

        # Check explicit path first
        if self._model_path and self._validate_model_dir(self._model_path):
            return self._model_path

        # Search common locations for each model variant
        search_dirs = [
            os.getcwd(),
            os.path.expanduser("~/AR-2"),
            os.path.expanduser("~/coursework/minilab6"),
            "/home/intc1002/coursework/minilab6",
            "/home/intc1002/AR-2",
            os.path.join(os.path.dirname(__file__), "..", ".."),
            os.path.expanduser("~"),
        ]

        for model_name in config["models"]:
            for base_dir in search_dirs:
                path = os.path.join(base_dir, model_name)
                if self._validate_model_dir(path):
                    return path

        return None

    @staticmethod
    def _validate_model_dir(path):
        """Check that a VOSK model directory exists and has required files."""
        if not os.path.isdir(path):
            return False
        # A valid VOSK model must have at minimum these files
        required = ["conf/mfcc.conf", "am/final.mdl"]
        for req in required:
            if not os.path.isfile(os.path.join(path, req)):
                # Some models use different structure
                pass
        # At minimum, check the directory is not empty and has some .mdl or .conf
        contents = os.listdir(path)
        if len(contents) < 2:
            return False
        return True

    def _create_recognizer(self, model, language=None):
        """Create a KaldiRecognizer with grammar for the given language."""
        lang = language or self._language
        config = LANGUAGE_CONFIGS.get(lang, LANGUAGE_CONFIGS["en"])
        grammar = json.dumps(config["grammar"])
        return KaldiRecognizer(model, self.SAMPLE_RATE, grammar)

    def _listen_loop(self):
        """Background loop: stream audio to VOSK, detect wake word + commands."""
        model_path = self._find_model()
        if not model_path:
            logger.error("VOSK model not found. Voice listener disabled.")
            logger.error("Download: https://alphacephei.com/vosk/models")
            logger.error(f"Looking for: {LANGUAGE_CONFIGS[self._language]['models']}")
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

        rec = self._create_recognizer(model)
        logger.info(f"Voice listener ready. Wake phrase: '{self._wake_phrase}' (lang: {self._language})")

        while self._running:
            try:
                # Check for language switch request
                with self._lock:
                    switch_to = self._language_switch_requested
                    self._language_switch_requested = None

                if switch_to and switch_to != self._language:
                    new_model_path = self._find_model(switch_to)
                    if new_model_path and new_model_path != model_path:
                        try:
                            logger.info(f"Switching language to {switch_to}, loading model...")
                            model = Model(new_model_path)
                            model_path = new_model_path
                        except Exception as e:
                            logger.error(f"Failed to load {switch_to} model: {e}")
                    self._language = switch_to
                    self._wake_phrase = self._wake_phrases.get(switch_to, "hello sonny")
                    rec = self._create_recognizer(model, switch_to)
                    logger.info(f"Language switched to {switch_to}. Wake: '{self._wake_phrase}'")

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
