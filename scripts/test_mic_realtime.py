#!/usr/bin/env python3
"""Real-time Pi mic test with speech-bubble UI.

This version reads the live RMS from the VoiceListener itself rather
than opening a second pyaudio stream — that was the cause of the
"level stuck near zero" we saw in the previous run (two clients
competing on the C-Media USB mic under PipeWire).

Also shows mic-gain diagnostics from amixer + wpctl so you can
spot if PipeWire is silently lowering the source volume.

Controls: ESC to quit.
"""
import os
import sys
import time
import threading
import collections
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import pygame
except ImportError:
    print("pygame required: pip install pygame")
    sys.exit(1)

from alfred.voice.listener import VoiceListener
from alfred.voice.intent import IntentClassifier


def query_mixer():
    """Return a short one-line diagnostic of current mic gain state."""
    parts = []
    # amixer per-card: just card 0 Mic Capture Volume + AGC
    try:
        r = subprocess.run(["amixer", "-c", "0", "get", "Mic Capture Volume"],
                           capture_output=True, timeout=1, text=True)
        vals = [w for w in r.stdout.split() if w.startswith("[") and "%" in w]
        if vals:
            parts.append(f"amixer:{vals[0].strip('[]')}")
        r2 = subprocess.run(["amixer", "-c", "0", "get", "Auto Gain Control"],
                            capture_output=True, timeout=1, text=True)
        if "off" in r2.stdout.lower():
            parts.append("AGC:off")
        elif "on" in r2.stdout.lower():
            parts.append("AGC:ON!")
    except Exception:
        pass
    # wpctl default source volume
    try:
        r = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
                           capture_output=True, timeout=1, text=True)
        out = r.stdout.strip()
        if out:
            parts.append(f"wpctl:{out.split()[-1] if out.split() else '?'}")
    except Exception:
        pass
    return "  ".join(parts) or "(no mixer tools)"


class MicTestUI:
    W, H = 1000, 680
    BG = (15, 20, 30)
    FG = (230, 235, 245)
    DIM = (120, 130, 140)
    ACCENT = (90, 180, 255)
    OK = (100, 220, 120)
    WARN = (255, 180, 80)
    BAD = (230, 90, 110)

    def __init__(self, listener, noise_floor_guess=500):
        pygame.init()
        pygame.display.set_caption("Sonny Mic Test (ESC to quit)")
        self.screen = pygame.display.set_mode((self.W, self.H))
        self.f_big = pygame.font.SysFont("DejaVuSans", 28, bold=True)
        self.f_med = pygame.font.SysFont("DejaVuSans", 20)
        self.f_sml = pygame.font.SysFont("DejaVuSans", 16)
        self.f_mono = pygame.font.SysFont("DejaVuSansMono", 14)

        self.listener = listener
        self.noise_floor = noise_floor_guess
        self.state = "IDLE"
        self.utterances = collections.deque(maxlen=8)
        self.utter_start = 0.0
        self.utter_end = 0.0
        self._lock = threading.Lock()
        self.intent_cls = IntentClassifier()
        self.engine_label = "-"
        self.mixer_state = "?"
        self._mixer_last = 0.0

    def on_speech_start(self):
        with self._lock:
            if self.state == "IDLE":
                self.state = "SPEECH"
                self.utter_start = time.monotonic()

    def on_speech_end(self):
        with self._lock:
            self.state = "TRANSCRIBING"
            self.utter_end = time.monotonic()

    def on_transcript(self, text, engine):
        with self._lock:
            done = time.monotonic()
            latency_ms = int((done - self.utter_end) * 1000) if self.utter_end else 0
            intent, conf = self.intent_cls.classify(text)
            self.utterances.append({
                "text": text, "engine": engine,
                "latency_ms": latency_ms,
                "intent": intent, "conf": conf,
                "time": time.strftime("%H:%M:%S"),
            })
            self.state = "IDLE"
            self.engine_label = engine

    def draw(self):
        s = self.screen
        s.fill(self.BG)

        # Header
        s.blit(self.f_big.render("Sonny Pi Mic — Real-Time Test", True, self.FG), (20, 14))
        hint = self.f_sml.render("Say wake phrase + commands or random words. ESC to end.",
                                 True, self.DIM)
        s.blit(hint, (20, 52))

        rms = self.listener.current_rms or 0
        with self._lock:
            st = self.state
            eng = self.engine_label
            items = list(self.utterances)

        # Live RMS + threshold comparison
        # threshold = listener.SILENCE_THRESHOLD approximate
        threshold = getattr(self.listener, 'SILENCE_THRESHOLD', 500)
        # dynamic "speaking" indicator
        if rms > threshold * 1.3:
            if st == "IDLE":
                self.on_speech_start()

        # State pill
        color = {"IDLE": self.DIM, "SPEECH": self.OK, "TRANSCRIBING": self.ACCENT}[st]
        pygame.draw.rect(s, color, (20, 80, 190, 34), border_radius=8)
        s.blit(self.f_med.render(st, True, (0, 0, 0)), (32, 85))
        s.blit(self.f_sml.render(f"engine: {eng}", True, self.DIM), (220, 89))

        # RMS bar — show raw values so user can verify they rise when speaking
        max_display = max(self.noise_floor * 10, 4000)
        meter_w = 620
        pygame.draw.rect(s, (40, 50, 65), (20, 130, meter_w, 22), border_radius=4)
        lvl01 = min(rms / max_display, 1.0)
        bar_col = self.OK if rms > threshold else self.WARN if rms > threshold * 0.3 else self.BAD
        pygame.draw.rect(s, bar_col, (20, 130, int(meter_w * lvl01), 22), border_radius=4)
        # threshold marker line
        th_x = 20 + int(meter_w * min(threshold / max_display, 1.0))
        pygame.draw.line(s, self.FG, (th_x, 125), (th_x, 157), 2)
        s.blit(self.f_sml.render(f"rms={rms}  threshold={threshold}  (max scale={max_display})",
                                 True, self.FG), (650, 131))

        # Mixer diagnostic (polled every 2s on a separate thread)
        s.blit(self.f_sml.render(f"gain: {self.mixer_state}", True, self.DIM),
               (20, 162))

        # Utterance bubbles
        y = 200
        s.blit(self.f_med.render("Heard (newest first):", True, self.DIM), (20, y))
        y += 30
        for u in reversed(items):
            bubble = f'"{u["text"]}"'
            txt = self.f_med.render(bubble, True, self.FG)
            pad = 10
            box_w = min(txt.get_width() + pad * 2, self.W - 60)
            box_h = 34
            pygame.draw.rect(s, (30, 44, 60), (20, y, box_w, box_h), border_radius=12)
            s.blit(txt, (20 + pad, y + 6))
            meta = (f"{u['time']}  "
                    f"intent={u['intent']} ({u['conf']:.0%})  "
                    f"engine={u['engine']}  "
                    f"round-trip={u['latency_ms']} ms")
            meta_col = self.OK if u["latency_ms"] < 800 else self.WARN if u["latency_ms"] < 1500 else self.BAD
            s.blit(self.f_sml.render(meta, True, meta_col), (20, y + box_h + 2))
            y += box_h + 26
            if y > self.H - 40:
                break

        foot = self.f_sml.render("Mic: Pi USB (primary). Second stream OFF; uses listener's capture.",
                                 True, self.DIM)
        s.blit(foot, (20, self.H - 22))
        pygame.display.flip()

    def run(self, stop_event):
        clock = pygame.time.Clock()
        while not stop_event.is_set():
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    stop_event.set()
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                    stop_event.set()
            # Periodic mixer poll
            if time.monotonic() - self._mixer_last > 2.0:
                self.mixer_state = query_mixer()
                self._mixer_last = time.monotonic()
            self.draw()
            clock.tick(30)
        pygame.quit()


def main():
    listener = VoiceListener()
    # Force-wake so every utterance transcribes (no "Hello Sonny" gating)
    try:
        listener._awake = True
    except Exception:
        pass

    ui = MicTestUI(listener)
    stop_event = threading.Event()

    # Hook listener for speech-end + transcript
    orig_process_audio = listener._process_audio

    def wrapped(audio_data):
        ui.on_speech_end()
        orig_process_audio(audio_data)
        if ui.state != "IDLE":
            with ui._lock:
                ui.state = "IDLE"

    listener._process_audio = wrapped  # type: ignore

    def on_transcript(text):
        print(f"[mic] '{text}' ({listener.engine})")
        ui.on_transcript(text, listener.engine)

    listener.on_speech(on_transcript)
    listener.start()

    try:
        ui.run(stop_event)
    finally:
        listener.stop()
        print("\n--- test summary ---")
        for u in ui.utterances:
            print(f"  {u['time']}  lat={u['latency_ms']}ms  engine={u['engine']}  "
                  f"intent={u['intent']}({u['conf']:.0%})  '{u['text']}'")
        if ui.utterances:
            avg = sum(u["latency_ms"] for u in ui.utterances) / len(ui.utterances)
            print(f"  avg round-trip: {avg:.0f} ms  ({len(ui.utterances)} utterances)")


if __name__ == "__main__":
    main()
