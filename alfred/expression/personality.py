"""Personality engine — coordinates eyes, LEDs, head, and speaker by FSM state."""

import time
import logging

logger = logging.getLogger(__name__)


# Mapping from FSM state name to expression configuration
STATE_EXPRESSIONS = {
    "IDLE":        {"emotion": "neutral",   "led": "idle",        "head": "center"},
    "LISTEN":      {"emotion": "surprised", "led": "listening",   "head": "center"},
    "FOLLOW":      {"emotion": "neutral",   "led": "following",   "head": "center"},
    "ENDPOINT":    {"emotion": "surprised", "led": "following",   "head": "center"},
    "PARKING":     {"emotion": "happy",     "led": "parking",     "head": "center"},
    "ARUCO_SRCH":  {"emotion": "confused",  "led": "searching",   "head": "center"},
    "ARUCO_APPR":  {"emotion": "neutral",   "led": "approaching", "head": "track"},
    "BLOCKED":     {"emotion": "angry",     "led": "blocked",     "head": "center"},
    "REROUTE":     {"emotion": "confused",  "led": "searching",   "head": "center"},
    "PATROL":      {"emotion": "happy",     "led": "idle",        "head": "track"},
    "PERSON":      {"emotion": "happy",     "led": "approaching", "head": "track"},
    "DANCE":       {"emotion": "love",      "led": "dancing",     "head": "center"},
    "PHOTO":       {"emotion": "happy",     "led": "idle",        "head": "center"},
    "LOST_REV":    {"emotion": "confused",  "led": "error",       "head": "center"},
    "LOST_PIVOT":  {"emotion": "confused",  "led": "error",       "head": "center"},
    "STOPPING":    {"emotion": "neutral",   "led": "idle",        "head": "center"},
    "SLEEP":       {"emotion": "sleepy",    "led": "sleeping",    "head": "center"},
}


class PersonalityEngine:
    """Coordinates eyes, LEDs, head servo, and speaker to express robot state.

    Only updates expression subsystems on state transitions or when tracking
    data changes (e.g., new face detected). This avoids wasting cycles on
    redundant renders every tick.
    """

    def __init__(self, eyes=None, leds=None, head=None, speaker=None):
        """
        Args:
            eyes: EyeController instance or None.
            leds: LEDController instance or None.
            head: HeadController instance or None.
            speaker: Speaker instance or None.
        """
        self._eyes = eyes
        self._leds = leds
        self._head = head
        self._speaker = speaker
        self._last_state = None
        self._last_face_center = None
        self._last_eye_update = 0.0
        self._eye_update_interval = 0.1  # update eyes at 10Hz max (not 30Hz)

    def update(self, fsm_state, context=None):
        """Update all expression subsystems for the current FSM state.

        Only triggers full updates on state transitions. Eye gaze and head
        tracking update at a lower rate (10Hz) to avoid OLED/I2C bottleneck.

        Args:
            fsm_state: State name string (from STATE_NAMES).
            context: Optional dict with extra info, e.g.:
                     - "faces": list of detected faces for gaze tracking
                     - "speak": bool, whether to announce state change
        """
        context = context or {}
        now = time.monotonic()
        state_changed = fsm_state != self._last_state
        expr = STATE_EXPRESSIONS.get(fsm_state, STATE_EXPRESSIONS["IDLE"])

        # On state change: update LEDs and emotion immediately
        if state_changed:
            if self._eyes:
                self._eyes.set_emotion(expr["emotion"])
            if self._leds:
                self._leds.set_state(expr["led"])

        # Update eyes + head at reduced rate (10Hz) to avoid I2C bottleneck
        if now - self._last_eye_update >= self._eye_update_interval:
            self._last_eye_update = now

            if self._eyes:
                # Gaze tracking: look at detected person
                faces = context.get("faces")
                if faces and len(faces) > 0:
                    face = faces[0]
                    cx, cy = face.get("center", (320, 240))
                    frame_w = context.get("frame_width", 640)
                    frame_h = context.get("frame_height", 480)
                    self._eyes.look_at(cx / frame_w, cy / frame_h)
                    self._last_face_center = (cx, cy)
                else:
                    self._eyes.look_at(0.5, 0.5)
                    self._last_face_center = None
                self._eyes.update()

            # Update head tracking
            if self._head:
                faces = context.get("faces")
                if expr["head"] == "track" and faces and len(faces) > 0:
                    self._head.look_at_person(faces[0])
                elif expr["head"] == "center":
                    self._head.center()

        # Announce state changes via speaker (only on transition)
        if state_changed and self._speaker and context.get("speak", True):
            self._announce_state(fsm_state)

        self._last_state = fsm_state

    def _announce_state(self, state):
        """Speak a phrase for the new state."""
        announce_map = {
            "FOLLOW":     "follow",
            "STOPPING":   "stop",
            "DANCE":      "dance",
            "PHOTO":      "photo",
            "PATROL":     "patrol",
            "SLEEP":      "sleep",
            "LOST_REV":   "lost",
            "PARKING":    "arrived",
            "BLOCKED":    "blocked",
        }

        phrase_key = announce_map.get(state)
        if phrase_key:
            self._speaker.say(phrase_key)

    def express_greeting(self):
        """Play a greeting expression: happy eyes, rainbow LEDs, nod, speak."""
        if self._eyes:
            self._eyes.set_emotion("happy")
            self._eyes.update()
        if self._leds:
            self._leds.rainbow_cycle(speed=0.02, duration=2.0)
        if self._head:
            self._head.nod()
        if self._speaker:
            self._speaker.say("greet")

    def express_confusion(self):
        """Play a confused expression."""
        if self._eyes:
            self._eyes.set_emotion("confused")
            self._eyes.update()
        if self._head:
            self._head.shake()
        if self._speaker:
            self._speaker.say("confused")

    def express_goodbye(self):
        """Play a goodbye expression."""
        if self._eyes:
            self._eyes.set_emotion("happy")
            self._eyes.update()
        if self._head:
            self._head.nod(count=1)
        if self._speaker:
            self._speaker.say("goodbye")
