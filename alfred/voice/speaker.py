"""Speaker — text-to-speech and sound playback."""

import subprocess
import threading
import logging
import os

logger = logging.getLogger(__name__)

_HAS_PYGAME = False
try:
    import pygame
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    _HAS_PYGAME = True
except (ImportError, Exception):
    pass

# Detect available TTS engine
_TTS_ENGINE = None


def _find_piper_model():
    import glob as _glob
    search_paths = [
        os.path.join(os.getcwd(), "piper-voices", "*.onnx"),
        os.path.expanduser("~/.local/share/piper-voices/**/*.onnx"),
        os.path.join(os.getcwd(), "*.onnx"),
    ]
    for pattern in search_paths:
        matches = _glob.glob(pattern, recursive=True)
        if matches:
            return matches[0]
    return None


def _detect_tts():
    global _TTS_ENGINE
    if _TTS_ENGINE is not None:
        return _TTS_ENGINE

    try:
        subprocess.run(["piper", "--help"], capture_output=True, timeout=3)
        model = _find_piper_model()
        if model:
            _TTS_ENGINE = "piper"
            logger.info(f"TTS engine: piper (model: {model})")
            return _TTS_ENGINE
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        subprocess.run(["espeak-ng", "--version"], capture_output=True, timeout=3)
        _TTS_ENGINE = "espeak-ng"
        logger.info("TTS engine: espeak-ng")
        return _TTS_ENGINE
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        subprocess.run(["espeak", "--version"], capture_output=True, timeout=3)
        _TTS_ENGINE = "espeak"
        logger.info("TTS engine: espeak")
        return _TTS_ENGINE
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    _TTS_ENGINE = "none"
    logger.warning("No TTS engine found")
    return _TTS_ENGINE


class Speaker:
    """Text-to-speech with phrase lookup.

    Tries piper-tts first, falls back to espeak-ng/espeak.
    """

    PHRASES = {
        "greet": "Good day, I am Sonny. How may I help you?",
        "acknowledge": "Right away.",
        "confused": "I'm not sure I understand. Could you repeat that?",
        "goodbye": "Until next time. Take care!",
        "follow": "Following the track now.",
        "stop": "Stopping.",
        "dance": "Time to dance!",
        "photo": "Say cheese!",
        "patrol": "Starting patrol mode.",
        "sleep": "Going to sleep. Say Hello Sonny to wake me.",
        "lost": "I seem to have lost the line.",
        "arrived": "I have arrived at the destination.",
        "blocked": "Obstacle detected. Please clear the path.",
        "searching": "Searching for the marker.",
        "approaching": "Marker found. Approaching.",
        "path_clear": "Path clear. Resuming.",
        "person_greet": "Hello! How may I help you?",
        "delivery_ready": "I have arrived at the marker.",
        "awake": "I'm listening. What would you like me to do?",
    }

    def __init__(self, piper_voice=None, assets_dir=None):
        self._piper_voice = piper_voice or _find_piper_model()
        self._assets_dir = assets_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "sounds"
        )
        self._speaking = False
        self._lock = threading.Lock()

    @property
    def language(self):
        return "en"

    def say(self, text):
        """Speak text (non-blocking). Accepts phrase keys or raw text."""
        actual_text = self.PHRASES.get(text, text)
        thread = threading.Thread(target=self._speak_sync, args=(actual_text,), daemon=True)
        thread.start()

    def say_sync(self, text):
        """Speak text (blocking)."""
        actual_text = self.PHRASES.get(text, text)
        self._speak_sync(actual_text)

    def _speak_sync(self, text):
        with self._lock:
            self._speaking = True
            try:
                engine = _detect_tts()
                if engine == "piper":
                    # Pipe text safely without shell=True
                    piper_proc = subprocess.Popen(
                        ["piper", "--model", self._piper_voice, "--output-raw"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    )
                    aplay_proc = subprocess.Popen(
                        ["aplay", "-r", "22050", "-f", "S16_LE", "-c", "1"],
                        stdin=piper_proc.stdout, stderr=subprocess.DEVNULL,
                    )
                    piper_proc.stdin.write(text.encode())
                    piper_proc.stdin.close()
                    aplay_proc.wait(timeout=30)
                    piper_proc.wait(timeout=5)
                elif engine in ("espeak-ng", "espeak"):
                    try:
                        subprocess.run(
                            [engine, "-v", "mb-us1", "-s", "160", "-p", "40", text],
                            timeout=30, capture_output=True, check=True
                        )
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        subprocess.run(
                            [engine, "-s", "150", text],
                            timeout=30, capture_output=True
                        )
                else:
                    logger.info(f"[TTS] {text}")
            except subprocess.TimeoutExpired:
                logger.warning("TTS timed out")
            except Exception as e:
                logger.error(f"TTS error: {e}")
            finally:
                self._speaking = False

    def play_sound(self, name):
        if not _HAS_PYGAME:
            return
        for ext in ('.wav', '.mp3', '.ogg'):
            path = os.path.join(self._assets_dir, name + ext)
            if os.path.exists(path):
                try:
                    pygame.mixer.Sound(path).play()
                    return
                except Exception:
                    return

    @property
    def is_speaking(self):
        return self._speaking
