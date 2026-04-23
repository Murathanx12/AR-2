"""OpenAI Realtime API voice listener.

Streams 16 kHz PCM from the Pi USB mic over a WebSocket to the Realtime
session, uses server-side VAD to detect utterance boundaries, and
receives transcripts incrementally — so capture is never blocked by a
batch round-trip and the listener can still hear "stop" while a
previous transcript is being finalized.

Subclasses the batch VoiceListener so we inherit all the shared state
(`set_speaker`, `on_speech`, `put_to_sleep`, `is_awake`, `_do_wake`,
`last_text`, `engine`, wake-phrase handling, etc). Only `start` /
`stop` are overridden with the asyncio WebSocket loop.

Falls back: if the connection cannot be established at start, the
constructor raises — the FSM's instantiation then falls back to the
regular VoiceListener (batch Whisper path).
"""

import asyncio
import base64
import logging
import os
import threading
import time

from alfred.voice.listener import VoiceListener

logger = logging.getLogger(__name__)

REALTIME_MODEL = "gpt-4o-mini-realtime-preview"
TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"

# Short DECLARATIVE prompt — just introduces proper nouns so "Sonny"
# doesn't become "Sony" and "marker" doesn't become "market". A
# command-list prompt would get echoed verbatim on silence; this form
# is safe because models don't treat a factual sentence as a template.
SESSION_PROMPT = "The robot's name is Sonny. Markers are numbered."

# Phrases the model has been observed to emit on empty / ambiguous
# audio. A transcript matching one of these (case-insensitive) is
# dropped so we don't dispatch phantom commands.
HALLUCINATION_PHRASES = {
    "thank you.", "thanks.", "bye.", "bye!", "you.",
    "thanks for watching.", "thanks for watching",
    "thanks!", "thanks", "bye", "you",
    ".", "...", "",
    # Past prompt-echo text kept for safety.
    "hello sonny, follow the track, go to marker, dance, stop, patrol, photo.",
    SESSION_PROMPT.lower(),
    "the robot's name is sonny.",
    "markers are numbered.",
}


def is_hallucination(text):
    if not text:
        return True
    t = text.strip()
    if t.lower() in HALLUCINATION_PHRASES:
        return True
    # Non-ASCII in an English-only session usually means the model
    # flipped language on bad audio.
    if any(ord(c) > 127 for c in t):
        return True
    return False


class RealtimeVoiceListener(VoiceListener):
    """Streaming-WebSocket STT via gpt-4o-mini-transcribe."""

    SAMPLE_RATE = 16000
    CHUNK_MS = 100
    CHUNK_FRAMES = SAMPLE_RATE * CHUNK_MS // 1000

    def __init__(self, wake_phrase="hello sonny"):
        # Up-front capability check so the FSM can fall back if not met.
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY not set — realtime unavailable")
        try:
            import pyaudio  # noqa: F401
        except ImportError:
            raise RuntimeError("pyaudio not installed")
        try:
            from openai import AsyncOpenAI  # noqa: F401
        except ImportError:
            raise RuntimeError("openai SDK missing")

        super().__init__(wake_phrase=wake_phrase)
        self._engine = "realtime-" + TRANSCRIBE_MODEL
        self._loop_thread = None
        self._connected_once = False

    # ---- lifecycle ----

    def start(self):
        self._force_fixed_gain()
        self._running = True
        # Force-wake so the first utterance is accepted without the user
        # needing to say "Hello Sonny" on every boot. The wake-word gate
        # in _process() is still respected for the *sleep* intent.
        with self._lock:
            self._awake = True
        self._loop_thread = threading.Thread(target=self._run_asyncio, daemon=True)
        self._loop_thread.start()
        print("[Voice] Realtime listener starting (WebSocket STT)")

    def stop(self):
        self._running = False
        if self._loop_thread:
            self._loop_thread.join(timeout=3.0)

    # ---- asyncio plumbing ----

    def _run_asyncio(self):
        try:
            asyncio.run(self._main_async())
        except Exception as e:
            logger.error(f"Realtime asyncio exited: {e}")
            print(f"[Voice] Realtime exited: {e}")

    async def _main_async(self):
        backoff = 1.0
        while self._running:
            try:
                await self._run_session()
                backoff = 1.0
            except Exception as e:
                logger.warning(f"Realtime session error: {e}; reconnect in {backoff:.0f}s")
                print(f"[Voice] Realtime dropped: {e}  reconnect in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _run_session(self):
        from openai import AsyncOpenAI
        client = AsyncOpenAI()
        async with client.beta.realtime.connect(model=REALTIME_MODEL) as conn:
            await conn.send({
                "type": "session.update",
                "session": {
                    "modalities": ["text"],
                    "input_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": TRANSCRIBE_MODEL,
                        "language": "en",
                        "prompt": SESSION_PROMPT,
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 400,
                        "create_response": False,
                    },
                    "input_audio_noise_reduction": {"type": "near_field"},
                },
            })
            if not self._connected_once:
                print(f"[Voice] Realtime session ready "
                      f"(model={TRANSCRIBE_MODEL}, server-VAD)")
                self._connected_once = True
            await asyncio.gather(
                self._audio_pump(conn),
                self._event_recv(conn),
            )

    async def _audio_pump(self, conn):
        """Read from pyaudio, send PCM up the socket, respect TTS mute."""
        import audioop
        import pyaudio

        pa = pyaudio.PyAudio()
        # Scored device selection — same policy as the batch listener
        # (alfred/voice/listener.py). Prefer PnP / microphone / headset,
        # hard-negative the broken "USB2.0 Device" combo dongle, allow
        # pipewire/default as last-resort fallbacks. The previous version
        # of this listener fell through to `target_idx=0` when the name
        # search missed, which on this Pi is a 0-input-channel device →
        # `pa.open(channels=1, ...)` raises [Errno -9998] Invalid number
        # of channels and the realtime session goes dark.
        candidates = []
        for i in range(pa.get_device_count()):
            try:
                info = pa.get_device_info_by_index(i)
            except Exception:
                continue
            if info.get("maxInputChannels", 0) < 1:
                continue
            candidates.append((i, str(info.get("name", ""))))

        def _score(name: str) -> int:
            n = name.lower()
            if "usb2.0 device" in n:                return -10
            if "pnp" in n or "pcm2902" in n:        return 100
            if "microphone" in n or "mic" in n:     return 50
            if "headset" in n:                       return 40
            if "usb" in n:                           return 20
            if "pipewire" in n or "pulse" in n:      return 10
            if n == "default":                       return 3
            return 0

        attempts = []  # list of (label, idx, name, rate) to try in order
        if candidates:
            chosen_idx, chosen_name = max(candidates, key=lambda c: _score(c[1]))
            try:
                native_rate = int(
                    pa.get_device_info_by_index(chosen_idx)
                      .get("defaultSampleRate") or self.SAMPLE_RATE
                )
            except Exception:
                native_rate = self.SAMPLE_RATE
            # Try 16 kHz first (no resampling needed); fall back to native.
            for rate in {self.SAMPLE_RATE, native_rate}:
                attempts.append(("chosen", chosen_idx, chosen_name, rate))
        # PipeWire fallback — when the PnP mic is held by PipeWire (its
        # subdevice shows 0/1 in `arecord -l`), the only way to get the
        # audio is via the pipewire device, which routes through PW's
        # session manager and resamples to 16 kHz transparently.
        for i, name in candidates:
            if "pipewire" in name.lower():
                attempts.append(("pipewire", i, name, self.SAMPLE_RATE))
        for i, name in candidates:
            if name.lower() == "default":
                attempts.append(("default", i, name, self.SAMPLE_RATE))

        stream = None
        actual_rate = self.SAMPLE_RATE
        last_err = None
        for label, idx, name, rate in attempts:
            try:
                frames = self.CHUNK_FRAMES if rate == self.SAMPLE_RATE else \
                         int(rate * self.CHUNK_MS / 1000)
                stream = pa.open(
                    format=pyaudio.paInt16, channels=1, rate=rate,
                    input=True, input_device_index=idx,
                    frames_per_buffer=frames,
                )
                actual_rate = rate
                print(f"[Voice/RT] Using mic ({label}): idx={idx} {name!r} @ {rate} Hz")
                break
            except Exception as e:
                last_err = e
                print(f"[Voice/RT] mic idx={idx} ({label}) rejected @ {rate} Hz: {e}")
                continue
        if stream is None:
            print(f"[Voice/RT] No mic could be opened. Last error: {last_err}")
            pa.terminate()
            raise RuntimeError(f"realtime listener: no usable input device ({last_err})")
        self._actual_rate = actual_rate

        loop = asyncio.get_running_loop()
        resample_state = None
        last_gain_refresh = time.monotonic()
        # Adaptive gain-recovery state. PipeWire can dynamically lower the
        # source volume on the PnP mic ("ducking") which silently kills
        # voice. We track the recent peak RMS and force a re-pin whenever
        # the level has been flat-low for a while AND the speaker isn't
        # the one talking (because TTS-only audio is naturally quiet on
        # this mic when the speaker is on the other side of the robot).
        recent_peak = 0
        last_loud_time = time.monotonic()
        try:
            while self._running:
                data = await loop.run_in_executor(
                    None,
                    lambda: stream.read(stream._frames_per_buffer,
                                        exception_on_overflow=False),
                )
                if not data:
                    continue
                # Expose live RMS (for UIs / diagnostics).
                try:
                    with self._lock:
                        self._last_rms = audioop.rms(data, 2)
                except Exception:
                    pass
                # NOTE: mic stays open during TTS so a "stop" said over our
                # own announcement still reaches the API. Self-echo (the mic
                # picking up the speaker) is filtered on the receive side via
                # speaker.was_recently_said(). Previously this gate dropped
                # every audio frame while TTS was playing — that's why "stop"
                # never registered if the user spoke during a state-transition
                # announcement.
                if time.monotonic() < self._muted_until:
                    continue
                # Periodic gain re-pin (PipeWire can override amixer).
                # `_force_fixed_gain` spawns several `subprocess.run()` calls
                # (amixer + wpctl) that each take 50-500 ms. Running it
                # directly here BLOCKS the audio loop for the same window —
                # that's how the alfred build dropped to "near zero" mic
                # quality vs the standalone test. Offload to the executor
                # so the audio pump keeps reading PCM during the re-pin.
                now_t = time.monotonic()
                if now_t - last_gain_refresh > 5.0:
                    last_gain_refresh = now_t
                    loop.run_in_executor(None, self._force_fixed_gain)

                # Reactive re-pin: if peak RMS over the last ~3 s is well
                # below a typical voice/ambient floor (≤80 RMS units), force
                # an immediate re-pin. Skip while TTS is talking.
                if self._last_rms > recent_peak:
                    recent_peak = self._last_rms
                if self._last_rms > 80:
                    last_loud_time = now_t
                    recent_peak = self._last_rms
                tts_active = bool(self._speaker and self._speaker.is_speaking)
                if (not tts_active
                        and now_t - last_loud_time > 3.0
                        and recent_peak < 80):
                    print(f"[Voice/RT] reactive gain re-pin (peak={recent_peak} over 3s)")
                    last_gain_refresh = now_t
                    last_loud_time = now_t
                    recent_peak = 0
                    loop.run_in_executor(None, self._force_fixed_gain)
                # Resample to 16 kHz if needed.
                if actual_rate != self.SAMPLE_RATE:
                    data, resample_state = audioop.ratecv(
                        data, 2, 1, actual_rate, self.SAMPLE_RATE, resample_state,
                    )
                b64 = base64.b64encode(data).decode("ascii")
                try:
                    await conn.send({"type": "input_audio_buffer.append",
                                     "audio": b64})
                except Exception as e:
                    logger.warning(f"realtime send failed: {e}")
                    break
        finally:
            try:
                stream.stop_stream(); stream.close(); pa.terminate()
            except Exception:
                pass

    async def _event_recv(self, conn):
        async for event in conn:
            if not self._running:
                break
            et = getattr(event, "type", None) or (
                event.get("type") if isinstance(event, dict) else None)
            if et is None:
                continue
            if et == "conversation.item.input_audio_transcription.completed":
                text = (getattr(event, "transcript", None)
                        or (event.get("transcript", "")
                            if isinstance(event, dict) else "")
                        or "").strip()
                if is_hallucination(text):
                    logger.debug(f"[realtime] drop hallucination: {text!r}")
                    continue
                # Self-echo suppression: the mic stays open during TTS so we
                # can hear "stop" mid-announcement. Filter out the listener
                # transcribing our own speaker output. Exception: if the
                # transcript IS a stop word, always pass it through — even
                # if "stop" happens to appear in a recent TTS phrase, the
                # cost of acting on it is just an unnecessary stop.
                stripped = text.strip().lower().rstrip(".!,?")
                is_stop_word = stripped in ("stop", "halt", "freeze")
                if (not is_stop_word
                        and self._speaker
                        and self._speaker.was_recently_said(text)):
                    logger.debug(f"[realtime] drop self-echo: {text!r}")
                    continue
                with self._lock:
                    self._last_text = text
                logger.info(f"STT (realtime): '{text}'")
                print(f"[Voice|realtime] '{text}'")
                # Shared wake/stop/dispatch — defined on the parent class.
                self._process(text.lower())
            elif et == "error":
                err = getattr(event, "error", None) or (
                    event.get("error", {}) if isinstance(event, dict) else {})
                raise RuntimeError(f"realtime error event: {err}")
            # else: ignore session.* / speech_started / committed / etc.
