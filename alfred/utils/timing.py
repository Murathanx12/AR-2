"""Rate limiting and profiling utilities."""
import time

class RateTimer:
    """Maintains a fixed-rate loop."""
    def __init__(self, hz: float):
        self.period = 1.0 / hz
        self._next = 0.0

    def wait(self):
        now = time.monotonic()
        if self._next == 0.0:
            self._next = now + self.period
            return
        sleep_time = self._next - now
        if sleep_time > 0:
            time.sleep(sleep_time)
        self._next = time.monotonic() + self.period

class Stopwatch:
    """Simple profiling stopwatch."""
    def __init__(self):
        self._start = None
        self._laps = []

    def start(self):
        self._start = time.monotonic()
        self._laps = []
        return self

    def lap(self, label: str = "") -> float:
        elapsed = time.monotonic() - self._start
        self._laps.append((label, elapsed))
        return elapsed

    def elapsed(self) -> float:
        return time.monotonic() - self._start if self._start else 0.0

    def report(self) -> str:
        lines = [f"  {label or f'lap {i}'}: {t:.4f}s" for i, (label, t) in enumerate(self._laps)]
        return "\n".join(lines)
