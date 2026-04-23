#!/usr/bin/env python3
"""Realtime STT smoke test (OpenAI Realtime API, transcription-only mode).

Streams PCM16 16 kHz mono from the Pi USB mic over a WebSocket to
OpenAI. Uses the `gpt-4o-mini-transcribe` model with server-side VAD
so we never block capture waiting for a response. Emits each utterance
to a pygame bubble UI.

Why this matters vs the old listener:
  - No head-of-line blocking: the capture loop keeps feeding audio
    while previous utterances are being transcribed.
  - Server-side VAD is stricter than our energy heuristic, so random
    clicks/knocks don't trigger phantom transcripts.
  - Lower Pi RAM: no local faster-whisper model.
  - Interim deltas let us show the transcript as it forms.

Controls: ESC to quit.
"""
import os
import sys
import time
import base64
import threading
import asyncio
import collections
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

try:
    import pygame
    import pyaudio
    import audioop
    from openai import AsyncOpenAI
except ImportError as e:
    print(f"missing deps: {e}")
    sys.exit(1)

from alfred.voice.intent import IntentClassifier


# Audio config — Realtime API accepts pcm16 at 16k or 24k. 16k matches
# what the existing code uses and halves the upstream bandwidth.
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_MS = 100  # 100 ms chunks → 10 events/s, well under any rate limit
CHUNK_FRAMES = SAMPLE_RATE * CHUNK_MS // 1000


# Phrases the model has hallucinated on silent/ambiguous audio. If a
# transcript matches one of these exactly (case-insensitive) we drop it.
HALLUCINATION_PHRASES = {
    "thank you.", "thanks.", "bye.", "bye!", "you.",
    "thanks for watching.", "thanks for watching",
    ".", "...", "",
    # Previous prompt-echo text — kept for safety.
    "hello sonny, follow the track, go to marker, dance, stop, patrol, photo.",
    "the robot's name is sonny. markers are numbered.",
    "the robot's name is sonny.",
    "markers are numbered.",
}


def is_hallucination(text: str) -> bool:
    """True if a transcript should be discarded as a likely hallucination."""
    if not text:
        return True
    t = text.strip()
    if t.lower() in HALLUCINATION_PHRASES:
        return True
    # Non-ASCII in an English-only session usually means the model
    # flipped language on bad audio (we saw French creep in).
    if any(ord(c) > 127 for c in t):
        return True
    return False
# Realtime session model (for the WebSocket connection itself).
# The actual STT engine is configured in the session update below via
# `input_audio_transcription.model`.
MODEL = "gpt-4o-mini-realtime-preview"


class BubbleUI:
    W, H = 1000, 680
    BG = (15, 20, 30); FG = (230, 235, 245); DIM = (120, 130, 140)
    ACCENT = (90, 180, 255); OK = (100, 220, 120); WARN = (255, 180, 80); BAD = (230, 90, 110)

    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Sonny Realtime Mic (ESC to quit)")
        self.screen = pygame.display.set_mode((self.W, self.H))
        self.f_big = pygame.font.SysFont("DejaVuSans", 28, bold=True)
        self.f_med = pygame.font.SysFont("DejaVuSans", 20)
        self.f_sml = pygame.font.SysFont("DejaVuSans", 16)

        self.state = "CONNECTING"
        self.interim = ""         # current delta-building transcript
        self.utterances = collections.deque(maxlen=8)
        self.rms = 0
        self.speech_started_at = 0.0
        self.speech_ended_at = 0.0
        self.last_latency_ms = 0
        self.intent_cls = IntentClassifier()
        self._lock = threading.Lock()
        self.engine = MODEL

    def set_state(self, st):
        with self._lock:
            self.state = st

    def set_rms(self, rms):
        self.rms = rms

    def on_speech_started(self):
        with self._lock:
            self.state = "SPEECH"
            self.speech_started_at = time.monotonic()
            self.interim = ""

    def on_speech_stopped(self):
        with self._lock:
            self.state = "WAITING"
            self.speech_ended_at = time.monotonic()

    def on_delta(self, delta):
        with self._lock:
            self.interim += delta

    def on_completed(self, text):
        with self._lock:
            lat = int((time.monotonic() - self.speech_ended_at) * 1000) if self.speech_ended_at else 0
            intent, conf = self.intent_cls.classify(text)
            self.utterances.append({
                "text": text, "latency_ms": lat,
                "intent": intent, "conf": conf,
                "time": time.strftime("%H:%M:%S"),
            })
            self.interim = ""
            self.state = "LISTENING"
            self.last_latency_ms = lat

    def draw(self):
        s = self.screen
        s.fill(self.BG)
        s.blit(self.f_big.render("Sonny — Realtime API STT", True, self.FG), (20, 14))
        s.blit(self.f_sml.render(f"Model: {self.engine}   ESC to quit", True, self.DIM), (20, 52))

        with self._lock:
            st = self.state; items = list(self.utterances); interim = self.interim
        color = {"CONNECTING": self.WARN, "LISTENING": self.DIM,
                 "SPEECH": self.OK, "WAITING": self.ACCENT,
                 "ERROR": self.BAD, "DONE": self.DIM}.get(st, self.DIM)
        pygame.draw.rect(s, color, (20, 80, 190, 34), border_radius=8)
        s.blit(self.f_med.render(st, True, (0, 0, 0)), (32, 85))

        # RMS bar
        meter_w = 620
        pygame.draw.rect(s, (40, 50, 65), (20, 130, meter_w, 22), border_radius=4)
        lvl = min(self.rms / 5000.0, 1.0)
        pygame.draw.rect(s, self.OK if self.rms > 400 else self.WARN,
                         (20, 130, int(meter_w * lvl), 22), border_radius=4)
        s.blit(self.f_sml.render(f"rms={self.rms}", True, self.FG), (650, 131))

        # Interim transcript (live, while speaking)
        s.blit(self.f_med.render("Live transcript:", True, self.DIM), (20, 170))
        pygame.draw.rect(s, (30, 44, 60), (20, 198, self.W - 40, 44), border_radius=10)
        if interim:
            txt = self.f_med.render(f'"{interim}"', True, self.ACCENT)
            s.blit(txt, (30, 206))

        # Utterance bubbles
        y = 260
        s.blit(self.f_med.render("Heard (newest first):", True, self.DIM), (20, y))
        y += 30
        for u in reversed(items):
            bubble = f'"{u["text"]}"'
            txt = self.f_med.render(bubble, True, self.FG)
            pad = 10; box_w = min(txt.get_width() + pad * 2, self.W - 60); box_h = 34
            pygame.draw.rect(s, (30, 44, 60), (20, y, box_w, box_h), border_radius=12)
            s.blit(txt, (20 + pad, y + 6))
            meta = (f"{u['time']}  intent={u['intent']} ({u['conf']:.0%})  "
                    f"server latency={u['latency_ms']} ms")
            meta_col = self.OK if u["latency_ms"] < 400 else self.WARN if u["latency_ms"] < 1000 else self.BAD
            s.blit(self.f_sml.render(meta, True, meta_col), (20, y + box_h + 2))
            y += box_h + 26
            if y > self.H - 40: break

        s.blit(self.f_sml.render("No local Whisper. All STT via OpenAI Realtime (WebSocket).",
                                 True, self.DIM), (20, self.H - 22))
        pygame.display.flip()


def open_pi_mic():
    """Open the USB PnP mic at 16kHz mono. Same device picker as the listener."""
    pa = pyaudio.PyAudio()
    target_idx = 0
    # Find PnP mic explicitly (skip the bad USB2.0 combo on this Pi)
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        name = (info.get("name") or "").lower()
        if info.get("maxInputChannels", 0) <= 0:
            continue
        if "pnp" in name or "pcm2902" in name:
            target_idx = i
            break
    info = pa.get_device_info_by_index(target_idx)
    native_rate = int(info.get("defaultSampleRate") or SAMPLE_RATE)
    print(f"[mic] idx={target_idx} '{info['name']}' native_rate={native_rate}")
    # Try 16k first; fall back to native and downsample in Python
    try:
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                         input=True, input_device_index=target_idx,
                         frames_per_buffer=CHUNK_FRAMES)
        return pa, stream, SAMPLE_RATE
    except OSError:
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=native_rate,
                         input=True, input_device_index=target_idx,
                         frames_per_buffer=int(native_rate * CHUNK_MS / 1000))
        return pa, stream, native_rate


async def realtime_loop(ui: BubbleUI, stop_event: threading.Event):
    """Main async loop: WebSocket + audio pump."""
    client = AsyncOpenAI()
    print(f"[rt] connecting to model={MODEL} ...")
    try:
        conn_mgr = client.beta.realtime.connect(model=MODEL)
    except Exception as e:
        print(f"[rt] connect builder failed: {e}")
        ui.set_state("ERROR")
        return

    async with conn_mgr as conn:
        print("[rt] connected. configuring session ...")
        # Configure: server-VAD on, pcm16 in, text-only out (no TTS, no
        # chat response), transcription via gpt-4o-mini-transcribe.
        # NOTE on `prompt`: kept empty. A populated prompt causes the model
        # to echo the prompt verbatim on near-silent audio — we measured
        # this hallucinating the exact command list.
        await conn.send({
            "type": "session.update",
            "session": {
                "modalities": ["text"],
                "input_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "gpt-4o-mini-transcribe",
                    "language": "en",
                    # Short declarative prompt — just introduces proper
                    # nouns so the model doesn't map "Sonny"->"Sony" and
                    # "marker"->"market". Command-list prompts got echoed
                    # verbatim on silent audio; this form does not.
                    "prompt": "The robot's name is Sonny. Markers are numbered.",
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,           # OpenAI default — permissive
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 400, # slight bump from 350
                    "create_response": False,   # transcribe, don't reply
                },
                "input_audio_noise_reduction": {"type": "near_field"},
            },
        })
        ui.set_state("LISTENING")
        print("[rt] session ready. speak freely.")

        pa, stream, actual_rate = open_pi_mic()
        resample_state = None  # audioop.ratecv state

        # -------- sender task: pump audio --------
        async def pump_audio():
            loop = asyncio.get_running_loop()
            nonlocal resample_state
            while not stop_event.is_set():
                # Blocking read offloaded to executor
                data = await loop.run_in_executor(
                    None,
                    lambda: stream.read(stream._frames_per_buffer, exception_on_overflow=False),
                )
                if not data:
                    continue
                # RMS for UI meter
                try:
                    ui.set_rms(audioop.rms(data, 2))
                except Exception:
                    pass
                # Resample to 16k if needed
                if actual_rate != SAMPLE_RATE:
                    data, resample_state = audioop.ratecv(
                        data, 2, 1, actual_rate, SAMPLE_RATE, resample_state
                    )
                b64 = base64.b64encode(data).decode("ascii")
                try:
                    await conn.send({"type": "input_audio_buffer.append", "audio": b64})
                except Exception as e:
                    print(f"[rt] send failed: {e}")
                    break

        # -------- receiver: parse events --------
        async def recv_events():
            async for event in conn:
                et = getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)
                if et is None:
                    continue
                if et == "input_audio_buffer.speech_started":
                    ui.on_speech_started()
                elif et == "input_audio_buffer.speech_stopped":
                    ui.on_speech_stopped()
                elif et == "conversation.item.input_audio_transcription.delta":
                    delta = getattr(event, "delta", None) or event.get("delta", "")
                    if delta:
                        ui.on_delta(delta)
                elif et == "conversation.item.input_audio_transcription.completed":
                    text = (getattr(event, "transcript", None)
                            or (event.get("transcript", "") if isinstance(event, dict) else "")
                            or "").strip()
                    if is_hallucination(text):
                        print(f"[rt] DROP hallucination: {text!r}")
                        continue
                    print(f"[rt] DONE: {text!r}")
                    ui.on_completed(text)
                elif et == "error":
                    err = getattr(event, "error", None) or event.get("error", {})
                    print(f"[rt] ERROR event: {err}")
                    ui.set_state("ERROR")
                elif et in ("session.created", "session.updated",
                            "transcription_session.created", "transcription_session.updated",
                            "input_audio_buffer.committed"):
                    print(f"[rt] {et}")
                # else: ignore (rate-limits, other noise)

        try:
            await asyncio.gather(pump_audio(), recv_events())
        finally:
            try: stream.stop_stream(); stream.close(); pa.terminate()
            except Exception: pass


def main():
    ui = BubbleUI()
    stop_event = threading.Event()

    # Start the asyncio loop on a thread so pygame can own the main thread
    def run_async():
        try:
            asyncio.run(realtime_loop(ui, stop_event))
        except Exception as e:
            print(f"[rt] fatal: {e}")
            ui.set_state("ERROR")
    async_thread = threading.Thread(target=run_async, daemon=True)
    async_thread.start()

    clock = pygame.time.Clock()
    try:
        while not stop_event.is_set():
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    stop_event.set()
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                    stop_event.set()
            ui.draw()
            clock.tick(30)
    finally:
        stop_event.set()
        pygame.quit()
        print("\n--- session summary ---")
        for u in ui.utterances:
            print(f"  {u['time']}  lat={u['latency_ms']}ms  "
                  f"intent={u['intent']}({u['conf']:.0%})  '{u['text']}'")
        if ui.utterances:
            avg = sum(u["latency_ms"] for u in ui.utterances) / len(ui.utterances)
            print(f"  avg server latency: {avg:.0f} ms")


if __name__ == "__main__":
    main()
