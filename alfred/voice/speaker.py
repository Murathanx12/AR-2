"""Speaker — text-to-speech and sound playback."""

import subprocess
import threading
import logging
import os

logger = logging.getLogger(__name__)

try:
    import pygame
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    _HAS_PYGAME = True
except (ImportError, Exception):
    _HAS_PYGAME = False

# Detect available TTS engine
_TTS_ENGINE = None

def _find_piper_model():
    """Search for a piper .onnx voice model in common locations."""
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

    # Try piper first — but only if a model file actually exists
    try:
        subprocess.run(["piper", "--help"], capture_output=True, timeout=3)
        model = _find_piper_model()
        if model:
            _TTS_ENGINE = "piper"
            logger.info(f"TTS engine: piper (model: {model})")
            return _TTS_ENGINE
        else:
            logger.info("piper installed but no .onnx model found, skipping")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try espeak-ng
    try:
        subprocess.run(["espeak-ng", "--version"], capture_output=True, timeout=3)
        _TTS_ENGINE = "espeak-ng"
        logger.info("TTS engine: espeak-ng")
        return _TTS_ENGINE
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try espeak
    try:
        subprocess.run(["espeak", "--version"], capture_output=True, timeout=3)
        _TTS_ENGINE = "espeak"
        logger.info("TTS engine: espeak")
        return _TTS_ENGINE
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    _TTS_ENGINE = "none"
    logger.warning("No TTS engine found (tried piper, espeak-ng, espeak)")
    return _TTS_ENGINE


class Speaker:
    """Text-to-speech and sound playback.

    Tries piper-tts first, falls back to espeak-ng/espeak.
    Sound playback uses pygame.mixer.
    """

    PHRASES = {
        "greet": "Good day, I am Sonny. How may I help you?",
        "acknowledge": "Right away.",
        "confused": "I'm not sure I understand. Could you repeat that?",
        "goodbye": "Until next time. Take care!",
        "follow": "Following the track now.",
        "stop": "Stopping immediately.",
        "dance": "Time to dance!",
        "photo": "Say cheese!",
        "patrol": "Starting patrol mode.",
        "sleep": "Going to sleep. Say Hello Sonny to wake me.",
        "lost": "I seem to have lost the line. Let me find it.",
        "arrived": "I have arrived at the destination.",
        "blocked": "Something is in the way. Let me find another route.",
    }

    def __init__(self, piper_voice=None, assets_dir=None):
        """
        Args:
            piper_voice: Path to piper .onnx model, or None to auto-detect.
            assets_dir: Directory containing sound files. Defaults to assets/sounds/.
        """
        self._piper_voice = piper_voice or _find_piper_model()
        self._assets_dir = assets_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "sounds"
        )
        self._speaking = False
        self._lock = threading.Lock()

    def say(self, text):
        """Speak text using available TTS engine. Non-blocking.

        Args:
            text: Text string to speak, or a key from PHRASES dict.
        """
        # Resolve phrase keys
        actual_text = self.PHRASES.get(text, text)

        thread = threading.Thread(target=self._speak_sync, args=(actual_text,), daemon=True)
        thread.start()

    def say_sync(self, text):
        """Speak text synchronously (blocks until done)."""
        actual_text = self.PHRASES.get(text, text)
        self._speak_sync(actual_text)

    def _speak_sync(self, text):
        """Internal: run TTS synchronously."""
        with self._lock:
            self._speaking = True
            try:
                engine = _detect_tts()

                if engine == "piper":
                    subprocess.run(
                        f'echo "{text}" | piper --model {self._piper_voice} --output-raw | aplay -r 22050 -f S16_LE -c 1',
                        shell=True, timeout=30
                    )
                elif engine in ("espeak-ng", "espeak"):
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
        """Play a sound file from assets directory.

        Args:
            name: Sound file name (without extension — tries .wav, .mp3, .ogg).
        """
        if not _HAS_PYGAME:
            logger.warning(f"Cannot play sound '{name}': pygame not available")
            return

        for ext in ('.wav', '.mp3', '.ogg'):
            path = os.path.join(self._assets_dir, name + ext)
            if os.path.exists(path):
                try:
                    sound = pygame.mixer.Sound(path)
                    sound.play()
                    logger.debug(f"Playing sound: {path}")
                    return
                except Exception as e:
                    logger.error(f"Sound playback error: {e}")
                    return

        logger.warning(f"Sound file not found: {name}")

    def play_music(self, path):
        """Play background music file (streaming).

        Args:
            path: Path to music file.
        """
        if not _HAS_PYGAME:
            logger.warning("Cannot play music: pygame not available")
            return

        if not os.path.exists(path):
            logger.warning(f"Music file not found: {path}")
            return

        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            logger.debug(f"Playing music: {path}")
        except Exception as e:
            logger.error(f"Music playback error: {e}")

    def stop_music(self):
        """Stop currently playing music."""
        if _HAS_PYGAME:
            pygame.mixer.music.stop()

    @property
    def is_speaking(self):
        return self._speaking
