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
        # Track active child procs so stop() can kill them mid-utterance.
        self._active_piper = None
        self._active_aplay = None
        self._active_espeak = None
        # Generation counter: incremented on stop(); queued utterances with a
        # stale generation skip execution instead of speaking late.
        self._stop_gen = 0
        self._gen_lock = threading.Lock()

    @property
    def language(self):
        return "en"

    def say(self, text):
        """Speak text (non-blocking). Accepts phrase keys or raw text."""
        actual_text = self.PHRASES.get(text, text)
        with self._gen_lock:
            gen = self._stop_gen
        thread = threading.Thread(target=self._speak_sync, args=(actual_text, gen), daemon=True)
        thread.start()

    def say_sync(self, text):
        """Speak text (blocking)."""
        actual_text = self.PHRASES.get(text, text)
        self._speak_sync(actual_text)

    def stop(self):
        """Interrupt any active TTS and cancel queued utterances.

        Increments the stop generation so queued threads skip when they wake.
        Terminates any piper/aplay/espeak subprocess currently playing audio.
        """
        with self._gen_lock:
            self._stop_gen += 1
        for proc in (self._active_aplay, self._active_piper, self._active_espeak):
            if proc is None:
                continue
            try:
                proc.terminate()
            except Exception:
                pass
        self._active_piper = None
        self._active_aplay = None
        self._active_espeak = None
        self._speaking = False

    def _gen_is_current(self, gen):
        if gen is None:
            return True
        with self._gen_lock:
            return gen == self._stop_gen

    def _speak_sync(self, text, gen=None):
        # Drop if stop() happened between say() call and thread start.
        if not self._gen_is_current(gen):
            return

        with self._lock:
            # Re-check after queuing on the lock — the utterance ahead of us
            # may have been a long one and stop() fired while we waited.
            if not self._gen_is_current(gen):
                return
            self._speaking = True
            try:
                engine = _detect_tts()
                if engine == "piper":
                    piper_proc = subprocess.Popen(
                        ["piper", "--model", self._piper_voice, "--output-raw"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    )
                    aplay_proc = subprocess.Popen(
                        ["aplay", "-r", "22050", "-f", "S16_LE", "-c", "1"],
                        stdin=piper_proc.stdout, stderr=subprocess.DEVNULL,
                    )
                    self._active_piper = piper_proc
                    self._active_aplay = aplay_proc
                    try:
                        piper_proc.stdin.write(text.encode())
                        piper_proc.stdin.close()
                        aplay_proc.wait(timeout=30)
                        piper_proc.wait(timeout=5)
                    finally:
                        self._active_piper = None
                        self._active_aplay = None
                elif engine in ("espeak-ng", "espeak"):
                    try:
                        espeak_proc = subprocess.Popen(
                            [engine, "-v", "mb-us1", "-s", "160", "-p", "40", text],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                        self._active_espeak = espeak_proc
                        espeak_proc.wait(timeout=30)
                        if espeak_proc.returncode not in (0, None):
                            raise subprocess.CalledProcessError(espeak_proc.returncode, engine)
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        espeak_proc = subprocess.Popen(
                            [engine, "-s", "150", text],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                        self._active_espeak = espeak_proc
                        espeak_proc.wait(timeout=30)
                    finally:
                        self._active_espeak = None
                else:
                    logger.info(f"[TTS] {text}")
            except subprocess.TimeoutExpired:
                logger.warning("TTS timed out")
            except Exception as e:
                logger.error(f"TTS error: {e}")
            finally:
                self._speaking = False
                self._active_piper = None
                self._active_aplay = None
                self._active_espeak = None

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
