"""Voice listener — speech-to-text with Google STT (primary), Whisper (fallback), or VOSK.

Priority order:
1. Google Speech Recognition (cloud, most accurate, handles accents)
2. Whisper tiny (offline, good accuracy)
3. VOSK (offline, grammar-constrained, lowest accuracy)

Design:
- Record audio, detect silence (energy-based VAD)
- Send complete utterance to STT engine for transcription
- Wake word "Hello Sonny" only needed once, then stays awake
- "stop" always works, even before wake
- Mic mutes during TTS to prevent echo
"""

import threading
import time
import logging
import json
import os
import struct
import math
import io
import wave

logger = logging.getLogger(__name__)

try:
    import pyaudio
    _HAS_PYAUDIO = True
except (ImportError, OSError):
    _HAS_PYAUDIO = False

# Google Speech Recognition (best accuracy for accented English)
_HAS_GOOGLE_STT = False
try:
    import speech_recognition as sr
    _HAS_GOOGLE_STT = True
    logger.info("Google Speech Recognition available")
except ImportError:
    pass

# Try Whisper (secondary — offline fallback)
_HAS_WHISPER = False
_whisper_model = None
try:
    from faster_whisper import WhisperModel
    _HAS_WHISPER = True
    logger.info("faster-whisper available")
except ImportError:
    try:
        import whisper as _openai_whisper
        _HAS_WHISPER = True
        logger.info("openai-whisper available")
    except ImportError:
        pass

# VOSK as fallback
_HAS_VOSK = False
try:
    from vosk import Model as VoskModel, KaldiRecognizer
    _HAS_VOSK = True
except ImportError:
    pass


WAKE_VARIANTS = {
    "hello sonny", "hello sunny", "hello sony", "hello son",
    "hallo sonny", "hallo sunny", "halo sonny", "halo sunny",
    "hey sonny", "hey sunny", "hey sony",
    "hi sonny", "hi sunny", "hi sony",
}

WAKE_MAYBE = {"hello", "hallo", "halo", "hey", "hi"}

# VOSK grammar fallback
VOSK_GRAMMAR = json.dumps([
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
    """STT listener: Whisper tiny (primary) with VOSK fallback.

    Uses energy-based VAD to detect when you stop speaking,
    then transcribes the complete utterance.
    """

    SAMPLE_RATE = 16000
    CHUNK_SIZE = 1024         # ~64ms per chunk at 16kHz
    SILENCE_THRESHOLD = 1000  # RMS energy below this = silence (high = ignore background noise)
    SILENCE_DURATION = 0.5    # seconds of silence to end utterance
    MIN_SPEECH_DURATION = 0.3 # minimum speech to process (ignore clicks/noise)
    MAX_SPEECH_DURATION = 5   # max 5 seconds per utterance (commands are short)
    NOISE_FLOOR_FRAMES = 50   # frames to measure ambient noise level at startup

    def __init__(self, wake_phrase="hello sonny", model_path=None):
        self._model_path = model_path
        self._running = False
        self._callback = None
        self._thread = None
        self._speaker = None
        self._engine = None  # "whisper" or "vosk"

        self._lock = threading.Lock()
        self._awake = False
        self._wake_detected = False
        self._last_text = ""
        self._muted_until = 0

    @property
    def language(self):
        return "en"

    @property
    def engine(self):
        return self._engine or "none"

    def set_speaker(self, speaker):
        self._speaker = speaker

    def start(self):
        if not _HAS_PYAUDIO:
            print("[Voice] pyaudio not installed - voice disabled")
            return
        if not _HAS_WHISPER and not _HAS_VOSK:
            print("[Voice] No STT engine (install faster-whisper or vosk)")
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

    @property
    def last_text(self):
        with self._lock:
            return self._last_text

    @property
    def is_awake(self):
        with self._lock:
            return self._awake

    # ---- Google STT ----

    def _transcribe_google(self, audio_data):
        """Transcribe audio bytes using Google Speech Recognition. Returns text string."""
        recognizer = sr.Recognizer()
        # Convert raw PCM to AudioData for speech_recognition
        audio = sr.AudioData(audio_data, self.SAMPLE_RATE, 2)  # 16-bit = 2 bytes
        try:
            text = recognizer.recognize_google(audio, language="en-US")
            return text.lower().strip()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as e:
            print(f"[Voice] Google STT network error: {e}")
            return None  # None = network failure, trigger fallback

    # ---- Whisper setup ----

    def _init_whisper(self):
        """Load Whisper tiny model. Returns True if successful."""
        global _whisper_model
        if _whisper_model is not None:
            return True
        try:
            from faster_whisper import WhisperModel
            print("[Voice] Loading Whisper tiny model (faster-whisper)...")
            _whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
            self._engine = "whisper"
            print("[Voice] Whisper tiny loaded - high accuracy mode")
            return True
        except ImportError:
            pass
        try:
            import whisper as _ow
            print("[Voice] Loading Whisper tiny model (openai-whisper)...")
            _whisper_model = _ow.load_model("tiny.en")
            self._engine = "whisper"
            print("[Voice] Whisper tiny loaded - high accuracy mode")
            return True
        except Exception as e:
            print(f"[Voice] Whisper load failed: {e}")
        return False

    def _transcribe_whisper(self, audio_data):
        """Transcribe audio bytes using Whisper. Returns text string."""
        global _whisper_model
        if _whisper_model is None:
            return ""

        # Convert raw PCM to WAV in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(audio_data)
        wav_buffer.seek(0)

        try:
            # faster-whisper API
            if hasattr(_whisper_model, 'transcribe') and hasattr(_whisper_model, 'model'):
                segments, _ = _whisper_model.transcribe(
                    wav_buffer, language="en", beam_size=1,
                    vad_filter=True,
                )
                return " ".join(s.text.strip() for s in segments).lower().strip()
            else:
                # faster-whisper returns (segments, info)
                segments, _ = _whisper_model.transcribe(
                    wav_buffer, language="en", beam_size=1,
                )
                return " ".join(s.text.strip() for s in segments).lower().strip()
        except Exception as e:
            logger.warning(f"faster-whisper transcribe failed: {e}")

        # openai-whisper API
        try:
            import numpy as np
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            result = _whisper_model.transcribe(
                audio_np, language="en", fp16=False,
                task="transcribe",
            )
            return result.get("text", "").lower().strip()
        except Exception as e:
            logger.error(f"Whisper transcribe error: {e}")
            return ""

    # ---- VOSK setup ----

    def _find_vosk_model(self):
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

    # ---- VAD (Voice Activity Detection) ----

    @staticmethod
    def _rms(data):
        """Calculate RMS energy of audio chunk."""
        count = len(data) // 2
        if count == 0:
            return 0
        shorts = struct.unpack(f"<{count}h", data)
        sum_sq = sum(s * s for s in shorts)
        return int(math.sqrt(sum_sq / count))

    # ---- Main loop ----

    def _listen_loop(self):
        # Try engines in priority order: Whisper > VOSK
        # (Local-only — no cloud APIs, works offline and in China)
        use_whisper = False
        vosk_rec = None

        if _HAS_WHISPER:
            use_whisper = self._init_whisper()

        if not use_whisper and _HAS_VOSK:
            model_path = self._find_vosk_model()
            if model_path:
                try:
                    model = VoskModel(model_path)
                    vosk_rec = KaldiRecognizer(model, self.SAMPLE_RATE, VOSK_GRAMMAR)
                    self._engine = "vosk"
                    print(f"[Voice] VOSK loaded from {model_path} (fallback mode)")
                except Exception as e:
                    print(f"[Voice] VOSK load failed: {e}")
                    return
            else:
                print("[Voice] No VOSK model found")
                return

        if not use_whisper and vosk_rec is None:
            print("[Voice] No STT engine available")
            print("[Voice] Install: pip install faster-whisper")
            return

        # Open mic
        p = pyaudio.PyAudio()
        try:
            stream = p.open(
                format=pyaudio.paInt16, channels=1,
                rate=self.SAMPLE_RATE, input=True,
                frames_per_buffer=self.CHUNK_SIZE,
            )
        except Exception as e:
            print(f"[Voice] Failed to open mic: {e}")
            p.terminate()
            return

        print(f"[Voice] Ready ({self._engine}). Say 'Hello Sonny' to wake up.")

        try:
            if use_whisper:
                self._vad_loop(stream, p)
            else:
                self._vosk_loop(stream, p, vosk_rec)
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
            print("[Voice] Listener stopped")

    def _vad_loop(self, stream, pyaudio_instance):
        """Main loop using energy-based VAD + noise calibration. Works with Google/Whisper."""
        # Calibrate noise floor for 1 second at startup
        print("[Voice] Calibrating noise level (1 second)...")
        noise_samples = []
        for _ in range(self.NOISE_FLOOR_FRAMES):
            try:
                data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                noise_samples.append(self._rms(data))
            except Exception:
                pass
        if noise_samples:
            avg_noise = sum(noise_samples) / len(noise_samples)
            # Set threshold to 2x average noise (must speak louder than background)
            self.SILENCE_THRESHOLD = max(600, int(avg_noise * 2.5))
            print(f"[Voice] Noise floor: {avg_noise:.0f} RMS, threshold set to: {self.SILENCE_THRESHOLD}")
        else:
            print(f"[Voice] Using default threshold: {self.SILENCE_THRESHOLD}")

        audio_buffer = bytearray()
        is_speaking = False
        silence_start = 0
        speech_start = 0

        while self._running:
            try:
                data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                if not data:
                    continue

                # Mute during TTS
                if self._speaker and self._speaker.is_speaking:
                    self._muted_until = time.monotonic() + 1.0
                    audio_buffer.clear()
                    is_speaking = False
                    continue
                if time.monotonic() < self._muted_until:
                    continue

                energy = self._rms(data)

                if energy > self.SILENCE_THRESHOLD:
                    # Speech detected
                    if not is_speaking:
                        is_speaking = True
                        speech_start = time.monotonic()
                        audio_buffer.clear()
                    audio_buffer.extend(data)
                    silence_start = 0

                    # Safety: max duration
                    if time.monotonic() - speech_start > self.MAX_SPEECH_DURATION:
                        self._process_audio(bytes(audio_buffer))
                        audio_buffer.clear()
                        is_speaking = False

                elif is_speaking:
                    # Silence after speech
                    audio_buffer.extend(data)
                    if silence_start == 0:
                        silence_start = time.monotonic()
                    elif time.monotonic() - silence_start >= self.SILENCE_DURATION:
                        # End of utterance
                        duration = time.monotonic() - speech_start
                        if duration >= self.MIN_SPEECH_DURATION:
                            self._process_audio(bytes(audio_buffer))
                        audio_buffer.clear()
                        is_speaking = False
                        silence_start = 0

            except Exception as e:
                logger.error(f"Voice error: {e}")
                time.sleep(0.5)

    def _process_audio(self, audio_data):
        """Transcribe audio with Whisper and process the text."""
        text = self._transcribe_whisper(audio_data)
        if not text:
            return

        # Filter out whisper hallucinations (common on silence)
        junk = {"you", "thank you", "thanks for watching", "bye", "...", "",
                "thank you.", "thanks.", "you.", "bye."}
        if text.rstrip(".!,") in junk or text in junk:
            return

        # Filter out long sentences — commands are max ~6 words
        # Background conversation like "i was taking all three by the next one" is not a command
        word_count = len(text.split())
        if word_count > 8:
            logger.debug(f"[Voice] Ignored (too long, {word_count} words): '{text}'")
            return

        with self._lock:
            self._last_text = text

        logger.info(f"STT ({self._engine}): '{text}'")
        print(f"[Voice|{self._engine}] '{text}'")
        self._process(text)

    def _vosk_loop(self, stream, pyaudio_instance, rec):
        """Fallback VOSK loop (grammar-constrained, streaming)."""
        while self._running:
            try:
                data = stream.read(self.CHUNK_SIZE * 4, exception_on_overflow=False)
                if not data:
                    continue

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
                    real_words = [w for w in text.split() if w != "[unk]" and len(w) > 1]
                    if not real_words:
                        continue

                    with self._lock:
                        self._last_text = text

                    print(f"[Voice|VOSK] '{text}'")
                    self._process(text)

            except Exception as e:
                logger.error(f"Voice error: {e}")
                time.sleep(0.5)

    # ---- Text processing (shared by both engines) ----

    def _process(self, text):
        words = set(text.split()) - {"the", "a", "to", "please", "can", "you",
                                      "i", "want", "would", "like", "it", "[unk]"}

        # "stop" always works
        if words & {"stop", "halt", "freeze"}:
            if self._callback:
                self._callback("stop")
            return

        # Already awake — everything is a command
        if self._awake:
            if self._callback:
                self._callback(text)
            return

        # Not awake — check wake word
        lower = text.lower()
        for wake in WAKE_VARIANTS:
            if wake in lower:
                after = lower.split(wake, 1)[-1].strip()
                self._do_wake(after)
                return

        # Bare "hello" etc or close variants
        if words and words.issubset(WAKE_MAYBE | {"sonny", "sunny", "sony", "son"}):
            self._do_wake("")
            return

    def _do_wake(self, command_after=""):
        with self._lock:
            self._awake = True
            self._wake_detected = True
        print("[Voice] AWAKE")
        if command_after and self._callback:
            self._callback(command_after)
