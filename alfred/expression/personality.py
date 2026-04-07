"""Personality engine — coordinates eyes, LEDs, head, and speaker by FSM state."""

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
    "ARUCO_APPR":  {"emotion": "neutral",   "led": "approaching", "head": "center"},
    "BLOCKED":     {"emotion": "angry",     "led": "blocked",     "head": "center"},
    "REROUTE":     {"emotion": "confused",  "led": "searching",   "head": "center"},
    "PATROL":      {"emotion": "happy",     "led": "idle",        "head": "center"},
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

    Called each FSM tick to update all expression subsystems based on the
    current state and context (e.g., detected faces for gaze tracking).
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
        self._spoken_states = set()  # track which states we've already announced

    def update(self, fsm_state, context=None):
        """Update all expression subsystems for the current FSM state.

        Args:
            fsm_state: State name string (from STATE_NAMES).
            context: Optional dict with extra info, e.g.:
                     - "faces": list of detected faces for gaze tracking
                     - "speak": bool, whether to announce state change
                     - "person_center": (x, y) for head tracking
        """
        context = context or {}
        expr = STATE_EXPRESSIONS.get(fsm_state, STATE_EXPRESSIONS["IDLE"])

        # Update eyes
        if self._eyes:
            self._eyes.set_emotion(expr["emotion"])

            # Gaze tracking: look at detected person
            faces = context.get("faces")
            if faces:
                face = faces[0]
                cx, cy = face.get("center", (0.5, 0.5))
                # Normalize to 0-1 range
                frame_w = context.get("frame_width", 640)
                frame_h = context.get("frame_height", 480)
                self._eyes.look_at(cx / frame_w, cy / frame_h)
            else:
                self._eyes.look_at(0.5, 0.5)  # look forward

            self._eyes.update()

        # Update LEDs
        if self._leds:
            self._leds.set_state(expr["led"])

        # Update head
        if self._head:
            if expr["head"] == "track" and context.get("faces"):
                self._head.look_at_person(context["faces"][0])
            elif expr["head"] == "center":
                self._head.center()

        # Announce state changes via speaker
        state_changed = fsm_state != self._last_state
        if state_changed and self._speaker and context.get("speak", True):
            self._announce_state(fsm_state)

        self._last_state = fsm_state

    def _announce_state(self, state):
        """Speak a phrase for the new state (only first time per state visit)."""
        # Map FSM states to speaker phrases
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
