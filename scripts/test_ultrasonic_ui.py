#!/usr/bin/env python3
"""Live HC-SR04 monitor with pygame UI.

Reads `DIST_C:` lines from the ESP32 over /dev/ttyAMA2 and shows the
distance as a large number plus a moving bar. ESC quits cleanly.

Use this to confirm the centre ultrasonic + level-shifter wiring works
end-to-end before launching alfred. If the value sticks at "NO ECHO"
the sensor / shifter / wiring is the suspect, not alfred.
"""
import sys
import time
import threading

import pygame
import serial

PORT = "/dev/ttyAMA2"
BAUD = 115200

W, H = 720, 480
BG = (15, 20, 30)
FG = (230, 235, 245)
DIM = (110, 120, 135)
OK = (90, 220, 130)
WARN = (255, 180, 80)
BAD = (230, 90, 110)


class UltrasonicReader(threading.Thread):
    """Daemon thread tailing the UART for DIST_C: lines."""

    def __init__(self):
        super().__init__(daemon=True)
        self._ser = serial.Serial(PORT, BAUD, timeout=0.05)
        self._lock = threading.Lock()
        self._dist_cm = -1.0      # last reading; -1.0 = no echo / not yet
        self._last_update = 0.0   # monotonic time of last good read
        self._running = True

    def run(self):
        buf = b""
        while self._running:
            try:
                chunk = self._ser.read(64)
            except OSError:
                continue
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line.startswith(b"DIST_C:"):
                    try:
                        v = float(line.split(b":", 1)[1])
                    except ValueError:
                        continue
                    with self._lock:
                        self._dist_cm = v
                        self._last_update = time.monotonic()

    def get(self):
        with self._lock:
            return self._dist_cm, self._last_update

    def stop(self):
        self._running = False
        try:
            self._ser.close()
        except Exception:
            pass


def colour_for(dist_cm: float) -> tuple:
    if dist_cm < 0:
        return BAD
    if dist_cm < 30:
        return BAD
    if dist_cm < 60:
        return WARN
    return OK


def main():
    pygame.init()
    pygame.display.set_caption("HC-SR04 Live (ESC to quit)")
    screen = pygame.display.set_mode((W, H))
    f_huge = pygame.font.SysFont("DejaVuSans", 200, bold=True)
    f_med = pygame.font.SysFont("DejaVuSans", 28)
    f_sml = pygame.font.SysFont("DejaVuSans", 18)

    reader = UltrasonicReader()
    reader.start()

    clock = pygame.time.Clock()
    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                running = False

        dist_cm, last_t = reader.get()
        age = time.monotonic() - last_t if last_t > 0 else 99.0
        col = colour_for(dist_cm)

        screen.fill(BG)

        # Big number
        if dist_cm < 0:
            label = "NO ECHO"
        elif age > 1.0:
            label = "STALE"
        else:
            label = f"{dist_cm:.1f}"
        surf = f_huge.render(label, True, col)
        rect = surf.get_rect(center=(W // 2, H // 2 - 30))
        screen.blit(surf, rect)

        # Units
        if dist_cm >= 0 and age <= 1.0:
            unit = f_med.render("cm", True, DIM)
            screen.blit(unit, unit.get_rect(midleft=(rect.right + 12, rect.centery + 30)))

        # Bar (0..200 cm)
        bar_w = W - 80
        bar_x, bar_y, bar_h = 40, H - 70, 30
        pygame.draw.rect(screen, (40, 50, 65), (bar_x, bar_y, bar_w, bar_h), border_radius=6)
        if dist_cm > 0 and age <= 1.0:
            frac = max(0.0, min(1.0, dist_cm / 200.0))
            pygame.draw.rect(screen, col, (bar_x, bar_y, int(bar_w * frac), bar_h), border_radius=6)

        # Footer
        msg = f"port={PORT}  baud={BAUD}  age={age:5.2f}s   ESC = quit"
        screen.blit(f_sml.render(msg, True, DIM), (40, H - 30))

        # Header
        screen.blit(f_med.render("Centre HC-SR04 (TRIG=GPIO8, ECHO=GPIO9)", True, FG),
                    (40, 30))

        pygame.display.flip()
        clock.tick(30)

    reader.stop()
    pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except serial.SerialException as e:
        print(f"Cannot open {PORT}: {e}", file=sys.stderr)
        sys.exit(1)
