"""ArUco approach controller — find, center, approach, and hold distance.

Behavior:
1. SEARCH: Rotate slowly scanning for marker
2. CENTER: Stop rotating, turn to face marker directly
3. APPROACH: Drive forward while staying centered
4. HOLD: Maintain distance — if marker moves, follow it

Logs centering errors and distance for debugging.
"""

import math
import time
import logging

logger = logging.getLogger(__name__)

# Import file logger if available
try:
    from alfred.web.app import log_event
except ImportError:
    def log_event(msg): pass


class ArucoApproach:
    """Drives toward an ArUco marker with center-first behavior.

    Distance is computed from marker pixel size using the pinhole model:
        distance_m = (physical_marker_m * focal_length_px) / pixel_size
    focal_length_px is approximated from frame width (≈0.8·width) — good
    enough for a ~20 cm stop target on typical USB webcams. Using real
    distance instead of raw pixel size keeps thresholds resolution-independent;
    the old pixel-based thresholds (STOP_SIZE=140) caused the robot to enter
    hold-mode and back up for any marker visible at 1920×1080.
    """

    # Physical geometry of the printed ArUco marker. Adjust to match whatever
    # marker size you're actually using.
    PHYSICAL_MARKER_M = 0.18     # 18 cm printed tag (measured)
    FOCAL_RATIO = 0.413          # calibrated 2026-04-23 at 1920x1080: 476 px @ 30 cm

    # Target stop distance 40 cm (user spec, 2026-04-23 evening — bumped up
    # from 30 cm because the printed marker is mounted on a stand whose
    # leading edge sits ahead of the tag itself; stopping at 30 cm clipped
    # the stand). Camera distance is authoritative for the stop. Ultrasonic
    # only shapes speed (slow < 60 cm) and triggers reroute when something
    # is between us and the marker.
    STOP_DIST_M = 0.40           # stop target — 40 cm clear of the stand
    HOLD_NEAR_M = 0.35           # closer than this → back up
    HOLD_FAR_M  = 0.48           # farther than this while holding → nudge forward
    APPROACH_REENGAGE_M = 0.55   # drifted past this → leave hold, re-approach

    # Centring tolerance: 20 % of half-frame = ~192 px at 1920×1080. Real
    # pose jitter on a steady marker is ±15-18 % at 1080p (motion blur +
    # detector noise); 20 % accommodates that without losing precision.
    CENTER_TOLERANCE = 0.20

    # Arrival debounce: the marker must stay inside the stop band AND
    # centred for this many seconds of continuous frames before we commit
    # to hold mode. Stops the buzzer/announcement from firing on a single
    # noisy frame at 30 cm — also kills early-stop during slight overshoot
    # since any deviation outside the band resets the timer.
    STOP_HOLD_SECONDS = 3.0

    def __init__(self):
        self._smooth_cx = None
        self._smooth_size = None
        self._alpha = 0.35  # EMA smoothing
        self._holding = False  # True when maintaining distance
        self._stop_band_since = None  # monotonic time we first entered stop band

    def _distance_m(self, pixel_size, frame_width):
        if pixel_size <= 0:
            return float("inf")
        focal_px = self.FOCAL_RATIO * frame_width
        return (self.PHYSICAL_MARKER_M * focal_px) / pixel_size

    def _forward_speed(self, dist_m):
        """Ramp: fast when far, creep through the final ~15 cm before the
        30 cm stop target so we don't overshoot into the hold band."""
        if dist_m > 1.0:
            return 40
        if dist_m > 0.60:
            return 30
        if dist_m > 0.45:
            return 20
        return 14

    def compute_visual_approach(self, marker, frame_width, frame_height,
                                 us_in_stop_zone: bool = False):
        """Compute motor command to approach marker.

        Logic:
        1. If marker not centered: rotate to center it (no forward motion)
        2. If centered: drive forward, slow down as we get closer
        3. If within STOP_DIST_M (or ultrasonic confirms stop): debounce → hold

        Always returns (vx, vy, omega). vx > 0 = forward, vx < 0 = reverse.

        `us_in_stop_zone` is the controller's debounced "the centre HC-SR04
        agrees we're in stop range" signal. Treated as equivalent to the
        camera's in-band check so the stop fires whichever sensor sees it
        first — matches the user's "use the ultrasonic too" requirement.
        """
        raw_cx, _ = marker["center"]
        raw_size = marker["size"]

        if self._smooth_cx is None:
            self._smooth_cx = raw_cx
            self._smooth_size = raw_size
        else:
            self._smooth_cx += self._alpha * (raw_cx - self._smooth_cx)
            self._smooth_size += self._alpha * (raw_size - self._smooth_size)

        cx = self._smooth_cx
        size = self._smooth_size

        cx_img = frame_width / 2.0
        error_x = (cx - cx_img) / (frame_width / 2.0)

        dist_m = self._distance_m(size, frame_width)
        log_event(f"ARUCO: cx_err={error_x:+.2f} size={size:.0f}px dist={dist_m:.2f}m hold={self._holding}")

        # === HOLD MODE: maintain distance ===
        if self._holding:
            if dist_m > self.APPROACH_REENGAGE_M:
                self._holding = False
                log_event(f"ARUCO: marker moved away (dist={dist_m:.2f}m), re-approaching")
            elif dist_m < self.HOLD_NEAR_M:
                # While backing up we still want the camera (facing forward)
                # to track the marker: if marker is to the right we spin
                # right (omega > 0), same convention line-follower uses.
                omega = int(20 * error_x)
                log_event(f"ARUCO: too close (dist={dist_m:.2f}m), backing up")
                return (-15, 0, omega)
            elif dist_m > self.HOLD_FAR_M:
                omega = int(15 * error_x)
                log_event(f"ARUCO: drifted out (dist={dist_m:.2f}m), nudging forward")
                return (10, 0, omega)
            else:
                if abs(error_x) > self.CENTER_TOLERANCE:
                    omega = int(20 * error_x)
                    return (0, 0, omega)
                return (0, 0, 0)

        # === STOP-BAND BEHAVIOUR ===
        # Inside the stop band, vx is *always* 0 — never drive forward, even
        # while correcting heading. Off-centre while in band → rotate in
        # place to centre. Centred + in band → start (or continue) the
        # STOP_HOLD_SECONDS debounce; commit to hold when sustained. Any
        # gross deviation (well outside band, very off-centre) resets the
        # timer so the next attempt needs a fresh 3 s.
        #
        # Hysteresis on the distance gate: enter at STOP_DIST_M, stay until
        # past HOLD_FAR_M. Without it, a steady marker whose camera-distance
        # estimate jitters around the threshold (0.39 ↔ 0.40 ↔ 0.41) would
        # trip "left stop band" every other tick and never confirm.
        # `us_in_stop_zone` short-circuits the whole gate — if the centre
        # ultrasonic agrees we're at the marker, we're in band regardless of
        # what the camera estimate says.
        if self._stop_band_since is None:
            in_band_camera = dist_m <= self.STOP_DIST_M
        else:
            in_band_camera = dist_m <= self.HOLD_FAR_M
        in_band = in_band_camera or us_in_stop_zone
        centred = abs(error_x) <= self.CENTER_TOLERANCE
        if in_band:
            if centred:
                now = time.monotonic()
                if self._stop_band_since is None:
                    self._stop_band_since = now
                    log_event(
                        f"ARUCO: in stop band (dist={dist_m:.2f}m), "
                        f"holding {self.STOP_HOLD_SECONDS:.0f}s for confirmation"
                    )
                elapsed = now - self._stop_band_since
                if elapsed >= self.STOP_HOLD_SECONDS:
                    self._holding = True
                    self._stop_band_since = None
                    log_event(f"ARUCO: arrived! held {elapsed:.1f}s @ {dist_m:.2f}m")
                return (0, 0, 0)
            # In band but off-centre: strafe + rotate to centre, no forward
            # motion. Mecanum strafe is faster and creates less motion blur
            # than pure rotation, so the marker detection stays clean
            # during the manoeuvre. `vy > 0` strafes right, so positive
            # error_x (marker on right) gets positive vy. omega keeps the
            # heading aligned for a smaller residual.
            if self._stop_band_since is not None:
                log_event(
                    f"ARUCO: drifted off centre while in band "
                    f"(err={error_x:+.2f}) — resetting hold timer"
                )
                self._stop_band_since = None
            vy = int(25 * error_x)
            vy = max(-20, min(20, vy))
            omega = int(15 * error_x)
            omega = max(-15, min(15, omega))
            return (0, vy, omega)
        if self._stop_band_since is not None:
            log_event(
                f"ARUCO: left stop band (dist={dist_m:.2f}m) — resetting hold timer"
            )
            self._stop_band_since = None

        # === CENTERING: turn + strafe to face marker ===
        # Mecanum lets us correct heading and lateral position in the same
        # tick. Use rotation as the primary correction (so the camera
        # actually points at the marker for the next detection), with
        # a smaller strafe (vy) to shorten the path. For small errors,
        # also keep moving forward — strafe + rotate while approaching.
        if abs(error_x) > self.CENTER_TOLERANCE:
            omega = int(30 * error_x)
            omega = max(-30, min(30, omega))
            vy = int(15 * error_x)
            vy = max(-15, min(15, vy))

            if abs(error_x) > 0.3:
                log_event(f"ARUCO: centering (err={error_x:+.2f}, omega={omega}, vy={vy})")
                return (0, vy, omega)

            speed = self._forward_speed(dist_m)
            return (speed, vy, omega)

        # === APPROACH: centered, drive forward ===
        speed = self._forward_speed(dist_m)
        log_event(f"ARUCO: approaching (speed={speed}, dist={dist_m:.2f}m)")
        return (speed, 0, 0)

    def is_holding(self):
        """Whether we've arrived and are maintaining distance."""
        return self._holding

    def reset(self):
        """Reset for new target."""
        self._smooth_cx = None
        self._smooth_size = None
        self._holding = False
        self._stop_band_since = None
