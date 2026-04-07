"""Voice listener — wake-word detection and speech-to-text."""

import threading
import time
import logging
import io
import wave

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
    _HAS_SD = True
except (ImportError, OSError):
    _HAS_SD = False
    logger.warning("sounddevice not available — voice listener disabled")

try:
    import numpy as np
    _HAS_NP = True
except ImportError:
    _HAS_NP = False

_whisper_model = None


def _get_whisper():
    """Lazy-load whisper model."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        import whisper
        _whisper_model = whisper.load_model("base")
        logger.info("Whisper model loaded")
        return _whisper_model
    except (ImportError, Exception) as e:
        logger.warning(f"Whisper unavailable: {e}")
        return None


class VoiceListener:
    """Listens for wake word and transcribes speech using Whisper.

    When hardware is unavailable, all methods are safe no-ops.
    """

    SAMPLE_RATE = 16000
    CHANNELS = 1
    CHUNK_SECONDS = 3  # record in 3-second chunks
    SILENCE_THRESHOLD = 0.02  # RMS below this = silence

    def __init__(self, wake_phrase="Hello Sonny"):
        self._wake_phrase = wake_phrase.lower()
        self._running = False
        self._callback = None
        self._thread = None
        self._wake_detected = False
        self._listening_for_command = False

    def start(self):
        """Start background listening thread."""
        if not _HAS_SD or not _HAS_NP:
            logger.warning("Cannot start voice listener: sounddevice/numpy not available")
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("Voice listener started")

    def stop(self):
        """Stop listening."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Voice listener stopped")

    def on_speech(self, callback):
        """Register callback for recognised speech: callback(text, intent)."""
        self._callback = callback

    def is_wake_word_detected(self):
        """Whether the wake word was detected in recent audio."""
        detected = self._wake_detected
        self._wake_detected = False  # consume the detection
        return detected

    def _listen_loop(self):
        """Background loop: record chunks, transcribe, check for wake word."""
        while self._running:
            try:
                audio = self._record_chunk()
                if audio is None:
                    time.sleep(0.5)
                    continue

                # Check if there's actual speech (not silence)
                rms = np.sqrt(np.mean(audio ** 2))
                if rms < self.SILENCE_THRESHOLD:
                    continue

                text = self._transcribe(audio)
                if not text:
                    continue

                text_lower = text.strip().lower()
                logger.debug(f"Heard: {text_lower}")

                # Check for wake word
                if self._wake_phrase in text_lower:
                    self._wake_detected = True
                    self._listening_for_command = True
                    logger.info("Wake word detected!")
                    # Extract command after wake phrase
                    idx = text_lower.find(self._wake_phrase)
                    command = text_lower[idx + len(self._wake_phrase):].strip()
                    if command and self._callback:
                        self._callback(command)
                elif self._listening_for_command:
                    # We heard the wake word before, now listening for command
                    if self._callback:
                        self._callback(text_lower)
                    self._listening_for_command = False

            except Exception as e:
                logger.error(f"Voice listener error: {e}")
                time.sleep(1.0)

    def _record_chunk(self):
        """Record a short audio chunk. Returns numpy array or None."""
        if not _HAS_SD:
            return None
        try:
            frames = int(self.SAMPLE_RATE * self.CHUNK_SECONDS)
            audio = sd.rec(frames, samplerate=self.SAMPLE_RATE,
                          channels=self.CHANNELS, dtype='float32')
            sd.wait()
            return audio.flatten()
        except Exception as e:
            logger.debug(f"Recording error: {e}")
            return None

    def _transcribe(self, audio):
        """Transcribe audio using Whisper. Returns text string or empty."""
        model = _get_whisper()
        if model is None:
            return ""
        try:
            result = model.transcribe(audio, language="en", fp16=False)
            return result.get("text", "")
        except Exception as e:
            logger.debug(f"Transcription error: {e}")
            return ""
