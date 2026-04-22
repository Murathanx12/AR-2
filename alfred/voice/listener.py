"""Voice listener — speech-to-text with OpenAI Whisper API, Google STT, or local fallbacks.

Priority order:
1. OpenAI Whisper API (cloud, best accuracy, handles noise/accents)
2. Google Speech Recognition (cloud, free, good accuracy)
3. Whisper tiny (offline, decent accuracy)
4. VOSK (offline, grammar-constrained, lowest accuracy)

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
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

try:
    import pyaudio
    _HAS_PYAUDIO = True
except (ImportError, OSError):
    _HAS_PYAUDIO = False

# OpenAI Whisper API (best quality, handles noise)
_HAS_OPENAI = False
_openai_client = None
try:
    from openai import OpenAI
    _key = os.environ.get("OPENAI_API_KEY")
    if _key:
        _openai_client = OpenAI(api_key=_key)
        _HAS_OPENAI = True
        logger.info("OpenAI Whisper API available")
except ImportError:
    pass

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
    SILENCE_THRESHOLD = 500   # RMS energy below this = silence (lowered for weak USB mics)
    SILENCE_DURATION = 0.25   # seconds of silence to end utterance (shorter = snappier stop)
    MIN_SPEECH_DURATION = 0.2 # minimum speech to process (ignore clicks/noise)
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
        # Actual sample rate negotiated with the mic. Many USB mics (PCM2902
        # etc.) only support 44.1/48 kHz natively and reject 16 kHz at the
        # ALSA hw layer. We record at whatever rate works and pass that to
        # the WAV encoder; OpenAI Whisper handles any sample rate.
        self._actual_rate = self.SAMPLE_RATE

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
        if not _HAS_OPENAI and not _HAS_GOOGLE_STT and not _HAS_WHISPER and not _HAS_VOSK:
            print("[Voice] No STT engine (set OPENAI_API_KEY or install faster-whisper/vosk)")
            return
        # Disable hardware AGC on every known-PCM2902 card and pin capture
        # volume high. Without this the mic gain slides down every time the
        # robot speaks; input loudness decays toward zero across a session.
        self._force_fixed_gain()
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    @staticmethod
    def _force_fixed_gain():
        """Turn off mic AGC + max out capture volume on any card that
        supports those controls. Runs once at listener startup."""
        import subprocess
        for card in range(6):
            try:
                subprocess.run(
                    ["amixer", "-c", str(card), "set", "Auto Gain Control", "off"],
                    capture_output=True, timeout=2,
                )
                subprocess.run(
                    ["amixer", "-c", str(card), "set", "Mic", "100%"],
                    capture_output=True, timeout=2,
                )
            except Exception:
                pass

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

    # ---- OpenAI Whisper API ----

    def _transcribe_openai_api(self, audio_data):
        """Transcribe audio using OpenAI Whisper API. Best accuracy, handles noise."""
        if not _openai_client:
            return None
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._actual_rate)  # pass the real capture rate
            wf.writeframes(audio_data)
        wav_buffer.seek(0)
        wav_buffer.name = "audio.wav"
        try:
            response = _openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=wav_buffer,
                language="en",
                prompt="Hello Sonny, follow the track, go to marker, dance, stop, patrol, photo",
            )
            text = response.text.strip().lower()
            logger.info(f"OpenAI Whisper API: '{text}'")
            return text
        except Exception as e:
            logger.warning(f"OpenAI Whisper API error: {e}")
            return None

    # ---- Google STT ----

    def _transcribe_google(self, audio_data):
        """Transcribe audio bytes using Google Speech Recognition. Returns text string."""
        recognizer = sr.Recognizer()
        audio = sr.AudioData(audio_data, self._actual_rate, 2)
        try:
            text = recognizer.recognize_google(audio, language="en-US")
            return text.lower().strip()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as e:
            print(f"[Voice] Google STT network error: {e}")
            return None
        except Exception as e:
            # SpeechRecognition needs the `flac` CLI to convert audio; if missing,
            # it raises a plain OSError — catch generically to avoid spamming the loop.
            logger.debug(f"Google STT unavailable: {e}")
            return None

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

        # Convert raw PCM to WAV in memory, preserving the actual capture
        # rate. faster-whisper resamples internally; openai-whisper too.
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self._actual_rate)
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
        use_cloud = _HAS_OPENAI or _HAS_GOOGLE_STT
        use_whisper = False
        vosk_rec = None

        if _HAS_OPENAI:
            self._engine = "openai-api"
            print("[Voice] Primary STT: OpenAI Whisper API")

        if _HAS_WHISPER:
            use_whisper = self._init_whisper()
            if not _HAS_OPENAI:
                print("[Voice] Primary STT: Whisper local")

        if not use_whisper and not use_cloud and _HAS_VOSK:
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

        if not use_cloud and not use_whisper and vosk_rec is None:
            print("[Voice] No STT engine available")
            print("[Voice] Set OPENAI_API_KEY or install faster-whisper")
            return

        # Open mic. Explicitly pick a working USB mic rather than the ALSA
        # default — this Pi has both a broken "USB2.0 Device" combo device
        # (card 1, stops capturing after first buffer) and a healthy "USB
        # PnP Sound Device" (card 3). Prefer PnP / microphone / headset in
        # the name; avoid names containing the broken combo's signature.
        p = pyaudio.PyAudio()
        chosen_idx = None
        chosen_name = None
        candidates = []
        for i in range(p.get_device_count()):
            try:
                info = p.get_device_info_by_index(i)
            except Exception:
                continue
            if info.get("maxInputChannels", 0) < 1:
                continue
            name = str(info.get("name", ""))
            candidates.append((i, name))
        def _score(name: str) -> int:
            n = name.lower()
            # Known-broken combo dongle on this Pi — one-buffer-then-silent
            # capture bug. Never pick it directly, and prefer pipewire (with
            # its own source-selection policy) over "default" (raw ALSA
            # default route, which lands right back on this same dongle).
            if "usb2.0 device" in n:       return -10
            if "pnp" in n:                  return 100
            if "microphone" in n or "mic" in n: return 50
            if "headset" in n:              return 40
            if "usb" in n:                  return 20
            if "pipewire" in n or "pulse" in n: return 10
            if "default" in n:              return 3
            return 0
        if candidates:
            chosen_idx, chosen_name = max(candidates, key=lambda c: _score(c[1]))
        # Try the chosen hw device at its NATIVE rate first. The PCM2902-
        # class USB mics on this Pi only support 44.1 kHz; opening at 16 kHz
        # would cause ALSA to refuse (caught as [Errno -9997]). We record
        # at whatever rate the device advertises, then pass that rate
        # through to the WAV header — OpenAI Whisper accepts any rate.
        # Pipewire/default are last-resort because pipewire on this Pi
        # has been observed routing its default source to the broken
        # card 1 combo dongle even when card 3 (PnP) is present.
        attempts = []
        if chosen_idx is not None:
            try:
                info = p.get_device_info_by_index(chosen_idx)
                native_rate = int(info.get("defaultSampleRate", self.SAMPLE_RATE))
            except Exception:
                native_rate = self.SAMPLE_RATE
            # Prefer native rate; fall back to 16 kHz if device supports both.
            rates_to_try = [native_rate]
            if native_rate != self.SAMPLE_RATE:
                rates_to_try.append(self.SAMPLE_RATE)
            for rate in rates_to_try:
                attempts.append(("chosen", chosen_idx, chosen_name, rate))
        for i, name in candidates:
            if "pipewire" in name.lower():
                attempts.append(("pipewire", i, name, self.SAMPLE_RATE))
        for i, name in candidates:
            if name.lower() == "default":
                attempts.append(("default", i, name, self.SAMPLE_RATE))

        stream = None
        last_err = None
        for label, idx, name, rate in attempts:
            try:
                stream = p.open(
                    format=pyaudio.paInt16, channels=1,
                    rate=rate, input=True,
                    input_device_index=idx,
                    frames_per_buffer=self.CHUNK_SIZE,
                )
                self._actual_rate = rate
                print(f"[Voice] Using mic ({label}): idx={idx} {name!r} @ {rate} Hz")
                break
            except Exception as e:
                last_err = e
                print(f"[Voice] mic idx={idx} ({label}) rejected @ {rate} Hz: {e}")
                continue
        if stream is None:
            print(f"[Voice] Failed to open any mic: {last_err}")
            p.terminate()
            return

        print(f"[Voice] Ready ({self._engine}). Say 'Hello Sonny' to wake up.")

        try:
            if use_cloud or use_whisper:
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
            # Set threshold to 1.5x average noise — low enough for weak USB mics
            self.SILENCE_THRESHOLD = max(300, int(avg_noise * 1.5))
            print(f"[Voice] Noise floor: {avg_noise:.0f} RMS, threshold set to: {self.SILENCE_THRESHOLD}")
        else:
            print(f"[Voice] Using default threshold: {self.SILENCE_THRESHOLD}")

        audio_buffer = bytearray()
        is_speaking = False
        silence_start = 0
        speech_start = 0
        was_tts_active = False
        last_gain_refresh = time.monotonic()

        def _drain():
            """Throw away any pyaudio frames that accumulated while we were
            elsewhere (transcribing, speaking). Without this, stale chunks
            are processed as fresh speech."""
            try:
                while stream.get_read_available() >= self.CHUNK_SIZE:
                    stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
            except Exception:
                pass

        while self._running:
            try:
                data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                if not data:
                    continue

                # TTS gate: while the speaker is actively playing audio we
                # don't process input (mic would hear the speaker and
                # transcribe it). The moment TTS ends, we drain pyaudio's
                # backlog and the VAD resumes from a clean slate. No
                # padding, no extension — just follow the speaker state.
                tts_active = bool(self._speaker and self._speaker.is_speaking)
                if tts_active:
                    audio_buffer.clear()
                    is_speaking = False
                    silence_start = 0
                    was_tts_active = True
                    continue
                if was_tts_active:
                    _drain()
                    was_tts_active = False

                # Periodic re-pin of mic gain — the PCM2902 or USB driver
                # sometimes drifts capture volume down across long sessions.
                if time.monotonic() - last_gain_refresh > 10.0:
                    self._force_fixed_gain()
                    last_gain_refresh = time.monotonic()

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
                        _drain()

                elif is_speaking:
                    # Silence after speech
                    audio_buffer.extend(data)
                    if silence_start == 0:
                        silence_start = time.monotonic()
                    elif time.monotonic() - silence_start >= self.SILENCE_DURATION:
                        # End of utterance → transcribe. The cloud call takes
                        # ~300-700 ms; during that time pyaudio's internal ring
                        # buffer fills with stale frames that we must drop
                        # before resuming VAD.
                        duration = time.monotonic() - speech_start
                        if duration >= self.MIN_SPEECH_DURATION:
                            self._process_audio(bytes(audio_buffer))
                        audio_buffer.clear()
                        is_speaking = False
                        silence_start = 0
                        _drain()

            except Exception as e:
                logger.error(f"Voice error: {e}")
                time.sleep(0.5)

    def _process_audio(self, audio_data):
        """Transcribe audio with best available engine. Priority: OpenAI API > Google > Whisper."""
        text = None

        if _HAS_OPENAI:
            text = self._transcribe_openai_api(audio_data)
            if text:
                self._engine = "openai-api"

        if not text and _HAS_GOOGLE_STT:
            text = self._transcribe_google(audio_data)
            if text:
                self._engine = "google"

        if not text and _HAS_WHISPER:
            text = self._transcribe_whisper(audio_data)
            if text:
                self._engine = "whisper"

        if not text:
            return

        # Filter out whisper hallucinations (common on silence — "you", "thank
        # you", "...", etc. that Whisper invents when given near-silent audio)
        junk = {"you", "thank you", "thanks for watching", "bye", "...", "",
                "thank you.", "thanks.", "you.", "bye.", "bye!", "thanks",
                "thanks!"}
        stripped = text.rstrip(".!,?").lower()
        if stripped in junk or text.lower() in junk:
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
                    self._muted_until = time.monotonic() + 0.2
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

        # Auto-wake on strong command keywords so the demo is forgiving when
        # the presenter forgets the wake phrase. Narrow keyword set to reduce
        # false triggers from ambient noise.
        COMMAND_KEYWORDS = {"follow", "marker", "aruco", "dance", "patrol",
                            "photo", "picture", "selfie", "wander"}
        if (words & COMMAND_KEYWORDS) or ("go to" in lower and "marker" in lower):
            logger.info(f"Auto-wake on command keyword: '{text}'")
            print(f"[Voice] Auto-wake on command: '{text}'")
            self._do_wake(text)
            return

        # Dropped — tell the user why so they aren't left guessing.
        logger.info(f"Ignored (not awake, no wake phrase): '{text}'")
        print(f"[Voice] (ignored — say 'Hello Sonny' first): '{text}'")

    def _do_wake(self, command_after=""):
        with self._lock:
            self._awake = True
            self._wake_detected = True
        print("[Voice] AWAKE")
        if command_after and self._callback:
            self._callback(command_after)
