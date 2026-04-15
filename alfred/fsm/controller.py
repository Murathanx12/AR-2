"""Alfred V4 FSM controller — main dispatch loop coordinating all subsystems."""

import time
import logging

from alfred.config import CONFIG
from alfred.fsm.states import State, STATE_NAMES
from alfred.comms.uart import UARTBridge
from alfred.comms.protocol import (
    cmd_stop, cmd_vector, cmd_led, cmd_led_pattern, cmd_buzzer,
    cmd_turn_left, cmd_turn_right, cmd_spin_left,
)
from alfred.navigation.line_follower import LineFollower, FollowState

logger = logging.getLogger(__name__)

# R5: LED color map per state — (r, g, b)
STATE_LED_COLORS = {
    State.IDLE:             (0, 0, 100),     # dim blue
    State.LISTENING:        (0, 100, 255),    # bright blue
    State.FOLLOWING:        (0, 255, 0),      # green
    State.ENDPOINT:         (0, 255, 100),    # green-cyan
    State.PARKING:          (0, 255, 200),    # cyan
    State.ARUCO_SEARCH:     (255, 255, 0),    # yellow
    State.ARUCO_APPROACH:   (255, 165, 0),    # orange
    State.BLOCKED:          (255, 0, 0),      # red
    State.REROUTING:        (255, 50, 0),     # red-orange
    State.PATROL:           (100, 0, 255),    # purple
    State.PERSON_APPROACH:  (255, 0, 255),    # magenta
    State.DANCING:          (255, 255, 255),  # white (rainbow pattern)
    State.PHOTO:            (255, 255, 255),  # white flash
    State.LOST_REVERSE:     (255, 100, 0),    # orange
    State.LOST_PIVOT:       (255, 100, 0),    # orange
    State.STOPPING:         (255, 0, 0),      # red
    State.SLEEPING:         (0, 0, 0),        # off
}

# R5: TTS announcements per state
STATE_ANNOUNCEMENTS = {
    State.LISTENING:        "I'm listening.",
    State.FOLLOWING:        "Following the track.",
    State.ARUCO_SEARCH:     "Searching for the marker.",
    State.ARUCO_APPROACH:   "Marker found. Approaching.",
    State.BLOCKED:          "Obstacle detected. Please clear the path.",
    State.REROUTING:        "Finding another way around.",
    State.PATROL:           "Starting patrol.",
    State.PERSON_APPROACH:  "I see someone. Coming over.",
    State.DANCING:          "Time to dance!",
    State.PHOTO:            "Say cheese!",
    State.STOPPING:         "Stopping.",
    State.SLEEPING:         "Going to sleep. Say Hello Sonny to wake me.",
    State.IDLE:             None,  # no announcement for idle
}

# Ultrasonic obstacle threshold (cm)
OBSTACLE_THRESHOLD_CM = 20.0


class AlfredFSM:
    """Central finite state machine that drives Sonny's behaviour.

    Coordinates UART communication, line following, vision, voice, and
    expression subsystems through a 17-state FSM dispatched at 30 Hz.
    Graceful degradation: missing hardware = skip that subsystem.
    """

    def __init__(self, config=None, headless=False, no_voice=False, no_camera=False):
        self.config = config or CONFIG
        self.headless = headless
        self.no_voice = no_voice
        self.no_camera = no_camera

        # Core subsystems (always created)
        self.uart = UARTBridge(
            port=self.config.uart.port,
            baud_rate=self.config.uart.baud_rate,
        )
        self.line_follower = LineFollower(speed=self.config.speed.default_speed)

        # Vision subsystems
        self.camera = None
        self.aruco_detector = None
        self.obstacle_detector = None
        self.person_detector = None
        self.bev = None

        if not no_camera:
            try:
                from alfred.vision.camera import CameraManager
                self.camera = CameraManager(
                    camera_index=self.config.vision.camera_index,
                    resolution=self.config.vision.resolution,
                    fps=self.config.vision.fps,
                )
            except Exception:
                pass
            try:
                from alfred.vision.aruco import ArucoDetector
                self.aruco_detector = ArucoDetector(
                    dict_name=self.config.vision.aruco_dict,
                )
            except Exception:
                pass
            try:
                from alfred.vision.obstacle import ObstacleDetector
                self.obstacle_detector = ObstacleDetector()
            except Exception:
                pass
            try:
                from alfred.vision.person import PersonDetector
                self.person_detector = PersonDetector()
            except Exception:
                pass
            try:
                from alfred.vision.bev import BirdEyeView
                self.bev = BirdEyeView(
                    src_points=self.config.vision.bev_src_points or None,
                    dst_points=self.config.vision.bev_dst_points or None,
                )
            except Exception:
                pass

        # Navigation subsystems
        self.aruco_approach = None
        self.obstacle_avoider = None
        self.patrol_controller = None

        try:
            from alfred.navigation.aruco_approach import ArucoApproach
            self.aruco_approach = ArucoApproach()
        except Exception:
            pass
        try:
            from alfred.navigation.obstacle_avoider import ObstacleAvoider
            self.obstacle_avoider = ObstacleAvoider()
        except Exception:
            pass
        try:
            from alfred.navigation.patrol import PatrolController
            self.patrol_controller = PatrolController()
        except Exception:
            pass

        # Voice subsystems
        self.voice_listener = None
        self.intent_classifier = None
        self.speaker = None
        self.conversation = None

        if not no_voice:
            try:
                from alfred.voice.listener import VoiceListener
                self.voice_listener = VoiceListener(
                    wake_phrase=self.config.voice.wake_phrase,
                )
            except Exception:
                pass
            try:
                from alfred.voice.intent import IntentClassifier
                self.intent_classifier = IntentClassifier()
            except Exception:
                pass
            try:
                from alfred.voice.speaker import Speaker
                self.speaker = Speaker()
            except Exception:
                pass
            try:
                from alfred.voice.conversation import ConversationEngine
                self.conversation = ConversationEngine(speaker=self.speaker)
            except Exception:
                pass

        # Expression subsystems
        self.eyes = None
        self.leds = None
        self.head = None
        self.personality = None

        try:
            from alfred.expression.eyes import EyeController
            self.eyes = EyeController(
                width=self.config.expression.oled_width,
                height=self.config.expression.oled_height,
                address=self.config.expression.oled_address,
            )
        except Exception:
            pass
        try:
            from alfred.expression.leds import LEDController
            self.leds = LEDController(
                count=self.config.expression.neopixel_count,
            )
        except Exception:
            pass
        try:
            from alfred.expression.head import HeadController
            self.head = HeadController(
                channel=self.config.expression.head_servo_channel,
                center=self.config.expression.head_center_angle,
                range_deg=self.config.expression.head_range,
            )
        except Exception:
            pass
        try:
            from alfred.expression.personality import PersonalityEngine
            self.personality = PersonalityEngine(
                eyes=self.eyes, leds=self.leds,
                head=self.head, speaker=self.speaker,
            )
        except Exception:
            pass

        # GUI (created externally via set_gui)
        self.gui = None

        self.state = State.IDLE
        self._running = False
        self._previous_state = None  # for resuming after obstacle

        # Per-state context
        self._dance_start = None
        self._dance_duration = 5.0
        self._photo_taken = False
        self._aruco_target_id = None
        self._last_aruco_pose = None
        self._last_frame = None
        self._last_faces = []
        self._last_obstacles = []
        self._pending_intent = None  # for yes/no confirmation of partial matches

        # Dispatch table
        self._tick_dispatch = {
            State.IDLE:             self._tick_idle,
            State.LISTENING:        self._tick_listening,
            State.FOLLOWING:        self._tick_following,
            State.ENDPOINT:         self._tick_endpoint,
            State.PARKING:          self._tick_parking,
            State.ARUCO_SEARCH:     self._tick_aruco_search,
            State.ARUCO_APPROACH:   self._tick_aruco_approach,
            State.BLOCKED:          self._tick_blocked,
            State.REROUTING:        self._tick_rerouting,
            State.PATROL:           self._tick_patrol,
            State.PERSON_APPROACH:  self._tick_person_approach,
            State.DANCING:          self._tick_dancing,
            State.PHOTO:            self._tick_photo,
            State.LOST_REVERSE:     self._tick_lost_reverse,
            State.LOST_PIVOT:       self._tick_lost_pivot,
            State.STOPPING:         self._tick_stopping,
            State.SLEEPING:         self._tick_sleeping,
        }

    def set_gui(self, gui):
        """Attach a DebugGUI instance."""
        self.gui = gui

    def start(self):
        """Open UART, start subsystems, enter IDLE state."""
        self.uart.open()

        if self.camera:
            self.camera.open()

        if self.voice_listener:
            self.voice_listener.on_speech(self._on_voice_command)
            self.voice_listener.start()

        self.state = State.IDLE
        self._running = True
        print(f"Sonny V4 online. State: {STATE_NAMES[self.state]}")

        # R5: Set initial LED color
        self._update_led(State.IDLE)

        if self.personality:
            self.personality.express_greeting()

        if self.speaker:
            self.speaker.say("greet")

    def stop(self):
        """Shut down all subsystems."""
        self._running = False
        self.uart.send(cmd_stop())
        self.uart.send(cmd_led(0, 0, 0))
        self.uart.close()

        if self.camera:
            self.camera.close()
        if self.voice_listener:
            self.voice_listener.stop()
        if self.leds:
            self.leds.off()
        if self.person_detector:
            try:
                self.person_detector.close()
            except Exception:
                pass

        if self.personality:
            self.personality.express_goodbye()

        print("Sonny V4 shutting down.")

    def transition(self, new_state: State):
        """Transition to a new state with R5 indicators."""
        if new_state == self.state:
            return
        old_name = STATE_NAMES[self.state]
        new_name = STATE_NAMES[new_state]
        print(f"[FSM] {old_name} -> {new_name}")

        self._previous_state = self.state
        self.state = new_state

        # R5: Update LED color for new state
        self._update_led(new_state)

        # R5: TTS announcement for state transition
        announcement = STATE_ANNOUNCEMENTS.get(new_state)
        if announcement and self.speaker:
            self.speaker.say(announcement)

    def _update_led(self, state):
        """Send LED color command for given state via UART."""
        color = STATE_LED_COLORS.get(state, (0, 0, 0))
        self.uart.send(cmd_led(*color))

        # Special patterns for certain states
        if state == State.DANCING:
            self.uart.send(cmd_led_pattern(2))  # rainbow
        elif state == State.BLOCKED:
            self.uart.send(cmd_led_pattern(3))  # blink red
        elif state == State.ARUCO_SEARCH:
            self.uart.send(cmd_led_pattern(4))  # breathe yellow
        elif state == State.SLEEPING:
            self.uart.send(cmd_led_pattern(4))  # breathe dim
            self.uart.send(cmd_led(0, 0, 30))
        else:
            self.uart.send(cmd_led_pattern(0))  # solid

    def _check_ultrasonic_obstacle(self) -> bool:
        """Check ultrasonic sensor for obstacles (R4).

        Returns True only if sensor is connected AND obstacle within threshold.
        Returns False if no sensor data (distance == -1).
        """
        dist = self.uart.get_distance()
        # -1 means no sensor reading (not connected or no echo)
        if dist < 0:
            return False
        return 0 < dist < OBSTACLE_THRESHOLD_CM

    def _check_camera_obstacle(self) -> bool:
        """Check camera-based obstacle detection (R4).

        Only triggers if a significant obstacle is detected in the center path.
        Requires multiple consecutive frames to avoid false positives from
        shadows or dark floor patches.
        """
        if not self.obstacle_detector or self._last_frame is None:
            return True  # no detector = assume clear
        return not self.obstacle_detector.is_path_clear(self._last_frame)

    def tick(self):
        """Run one FSM cycle: read sensors, dispatch state handler, update expression."""
        # Read camera frame (shared across states)
        if self.camera and self.camera.is_available:
            self._last_frame = self.camera.read_frame()
            if self.gui and self._last_frame is not None:
                self.gui.set_camera_frame(self._last_frame)

        # Dispatch state handler
        handler = self._tick_dispatch.get(self.state)
        if handler is not None:
            handler()

        # Update personality/expression
        if self.personality:
            context = {
                "faces": self._last_faces,
                "frame_width": self.config.vision.resolution[0],
                "frame_height": self.config.vision.resolution[1],
                "speak": True,
            }
            self.personality.update(STATE_NAMES[self.state], context)

    # -- Voice callback -----------------------------------------------------

    def _on_voice_command(self, text):
        """Handle a recognised voice command.

        Called for every sentence after wake word. Handles:
        - __confirm_wake__: listener heard just "hello", asks confirmation
        - stop: always works from any state
        - Partial matches (0.5 confidence): asks yes/no before executing
        - Exact matches (1.0 confidence): executes immediately
        """
        if not self.intent_classifier:
            return

        # Special signal from listener: bare "hello" heard, ask if talking to us
        if text == "__confirm_wake__":
            if self.speaker:
                self.speaker.say("Are you talking to me?")
            if self.gui:
                self.gui.set_voice_output("Are you talking to me?")
            return

        intent, confidence = self.intent_classifier.classify(text)
        print(f"[Voice] '{text}' -> {intent} ({confidence:.0%})")

        if self.gui:
            self.gui.set_voice_input(text, intent, confidence)

        # If we were waiting for a yes/no answer to a pending intent
        if self._pending_intent:
            pending = self._pending_intent
            self._pending_intent = None
            if intent == "confirm":
                # They said yes — execute the pending command
                print(f"[Voice] Confirmed: {pending}")
                self._execute_intent(pending)
            else:
                if self.speaker:
                    self.speaker.say("Okay, cancelled.")
                if self.gui:
                    self.gui.set_voice_output("Cancelled.")
            return

        # STOP always works immediately from any state
        if intent == "stop":
            self.uart.send(cmd_stop())
            self.line_follower.debug_vx = 0
            self.line_follower.debug_vy = 0
            self.line_follower.debug_omega = 0
            if self.speaker:
                self.speaker.say("stop")
            if self.gui:
                self.gui.set_voice_output("Stopping.")
            self.transition(State.IDLE)
            return

        # SLEEP puts the voice listener back to sleep too
        if intent == "sleep":
            if self.speaker:
                self.speaker.say("sleep")
            if self.voice_listener:
                self.voice_listener.put_to_sleep()
            self.transition(State.SLEEPING)
            return

        # Exact match — execute immediately
        if confidence >= 1.0:
            self._execute_intent(intent)
            return

        # Partial match — ask for confirmation
        if confidence >= 0.5:
            question = self.intent_classifier.get_confirmation_question(intent)
            if question:
                self._pending_intent = intent
                if self.speaker:
                    self.speaker.say(question)
                if self.gui:
                    self.gui.set_voice_output(question)
                print(f"[Voice] Asking confirmation for: {intent}")
                return
            else:
                # No question defined — just execute it
                self._execute_intent(intent)
                return

        # Unknown
        if self.speaker:
            self.speaker.say("confused")
        if self.gui:
            self.gui.set_voice_output(f"Didn't understand: {text}")

    def _execute_intent(self, intent):
        """Execute a confirmed intent — transition to the right state."""

        # EC3: Chat
        if intent == "chat" and self.conversation:
            self.conversation.handle("")
            return

        intent_to_state = {
            "follow_track": State.FOLLOWING,
            "go_to_aruco":  State.ARUCO_SEARCH,
            "dance":        State.DANCING,
            "take_photo":   State.PHOTO,
            "come_here":    State.PERSON_APPROACH,
            "patrol":       State.PATROL,
            "search":       State.ARUCO_SEARCH,
        }

        target = intent_to_state.get(intent)
        if not target:
            return

        confirmations = {
            "follow_track": "Following the track.",
            "go_to_aruco":  "Searching for the marker.",
            "dance":        "Time to dance!",
            "take_photo":   "Say cheese!",
            "come_here":    "Coming to you.",
            "patrol":       "Starting patrol.",
            "search":       "Searching for the marker.",
        }
        msg = confirmations.get(intent, "Got it.")
        if self.speaker:
            self.speaker.say(msg)
        if self.gui:
            self.gui.set_voice_output(msg)

        # Prepare state
        if target == State.FOLLOWING:
            self.line_follower.reset()
        elif target == State.DANCING:
            self._dance_start = time.monotonic()
        elif target == State.PHOTO:
            self._photo_taken = False
        elif target == State.ARUCO_SEARCH and self.aruco_approach:
            self.aruco_approach.reset()
        self.transition(target)

    # -- State tick handlers ------------------------------------------------

    def _tick_idle(self):
        """Wait for wake word. Once awake, commands come via callback directly."""
        if self.voice_listener and self.voice_listener.is_wake_word_detected():
            if self.speaker:
                self.speaker.say("awake")
            if self.personality:
                self.personality.express_greeting()
            self.transition(State.LISTENING)

    def _tick_listening(self):
        """Awake and waiting for commands. Stay here until a command arrives.
        Commands are handled by _on_voice_command callback — no timeout."""
        # Nothing to do here — commands arrive via the callback
        # and transition us to the appropriate state.
        pass

    def _tick_following(self):
        """Run line follower and mirror sub-FSM transitions."""
        # R4: Check ultrasonic obstacle (only if sensor connected)
        if self._check_ultrasonic_obstacle():
            self.transition(State.BLOCKED)
            return

        ir_bits = self.uart.get_ir_bits()
        command = self.line_follower.tick(ir_bits)
        self.uart.send(command)

        # Mirror sub-FSM state transitions
        if self.line_follower.finished:
            self.uart.send(cmd_buzzer(1000, 200))  # R5: beep on completion
            if self.speaker:
                self.speaker.say("arrived")
            self.transition(State.IDLE)
        elif self.line_follower.state == FollowState.ENDPOINT:
            self.transition(State.ENDPOINT)
        elif self.line_follower.state == FollowState.LOST_REVERSE:
            self.transition(State.LOST_REVERSE)
        elif self.line_follower.state == FollowState.LOST_PIVOT:
            self.transition(State.LOST_PIVOT)
        elif self.line_follower.state == FollowState.PARKING:
            self.transition(State.PARKING)
        elif self.line_follower.state == FollowState.FOLLOWING:
            self.transition(State.FOLLOWING)

    def _tick_endpoint(self):
        """Continue line follower through endpoint detection."""
        self._tick_following()

    def _tick_parking(self):
        """Continue line follower through parking manoeuvre."""
        self._tick_following()

    def _tick_aruco_search(self):
        """Scan for ArUco markers by rotating slowly."""
        # R4: Check ultrasonic obstacle while searching
        if self._check_ultrasonic_obstacle():
            self.transition(State.BLOCKED)
            return

        if self.aruco_detector and self._last_frame is not None:
            markers = self.aruco_detector.detect(self._last_frame)
            if markers:
                # Found a marker — start approach
                self._aruco_target_id = markers[0]["id"]
                self.transition(State.ARUCO_APPROACH)
                return

        # Slow rotation to scan for markers
        self.uart.send(cmd_vector(0, 0, 30))
        self.line_follower.debug_vx = 0
        self.line_follower.debug_vy = 0
        self.line_follower.debug_omega = 30

    def _tick_aruco_approach(self):
        """Drive toward detected ArUco marker using visual approach (R3)."""
        if not self.aruco_detector or not self.aruco_approach or self._last_frame is None:
            self.transition(State.IDLE)
            return

        # R4: Check ultrasonic obstacle while approaching
        if self._check_ultrasonic_obstacle():
            self.transition(State.BLOCKED)
            return

        markers = self.aruco_detector.detect(self._last_frame)
        target_marker = None
        for m in markers:
            if m["id"] == self._aruco_target_id:
                target_marker = m
                break

        if target_marker is None:
            # Lost the marker — go back to searching
            self.transition(State.ARUCO_SEARCH)
            return

        # Try calibrated approach first, fall back to visual-only
        pose = self.aruco_detector.estimate_pose(target_marker)
        if pose:
            # Calibrated approach
            if self.aruco_approach.is_arrived(pose["tvec"]):
                self._on_aruco_arrived()
                return
            vx, vy, omega = self.aruco_approach.compute_approach(pose["tvec"], pose["rvec"])
        else:
            # Visual-only approach (R3 — no camera calibration needed)
            h, w = self._last_frame.shape[:2]
            result = self.aruco_approach.compute_visual_approach(
                target_marker, w, h
            )
            if result is None:
                # Arrived
                self._on_aruco_arrived()
                return
            vx, vy, omega = result

        self.uart.send(cmd_vector(int(vx), int(vy), int(omega)))
        self.line_follower.debug_vx = int(vx)
        self.line_follower.debug_vy = int(vy)
        self.line_follower.debug_omega = int(omega)

    def _on_aruco_arrived(self):
        """Handle arrival at ArUco marker."""
        self.uart.send(cmd_stop())
        self.uart.send(cmd_buzzer(1200, 300))  # R5: arrival beep
        print(f">>> Arrived at ArUco marker {self._aruco_target_id}")
        if self.speaker:
            self.speaker.say("I have arrived at the marker. Your delivery is ready.")
        self.transition(State.IDLE)

    def _tick_blocked(self):
        """Stop and wait for obstacle to clear (R4)."""
        self.uart.send(cmd_stop())
        self.line_follower.debug_vx = 0
        self.line_follower.debug_vy = 0
        self.line_follower.debug_omega = 0

        # Check if path cleared — ultrasonic is the primary sensor
        ultrasonic_clear = not self._check_ultrasonic_obstacle()

        if ultrasonic_clear:
            if self.speaker:
                self.speaker.say("Path clear. Resuming.")
            # Resume the previous state
            if self._previous_state in (State.FOLLOWING, State.ENDPOINT, State.PARKING,
                                         State.LOST_REVERSE, State.LOST_PIVOT):
                self.line_follower.reset()
                self.transition(State.FOLLOWING)
            elif self._previous_state == State.ARUCO_APPROACH:
                self.transition(State.ARUCO_APPROACH)
            elif self._previous_state == State.ARUCO_SEARCH:
                self.transition(State.ARUCO_SEARCH)
            else:
                self.transition(State.IDLE)

    def _tick_rerouting(self):
        """Compute avoidance manoeuvre around obstacle."""
        if self.obstacle_avoider and self.obstacle_detector and self._last_frame is not None:
            obstacles = self.obstacle_detector.detect(self._last_frame)
            vx, vy, omega = self.obstacle_avoider.compute_avoidance(obstacles)

            if not self.obstacle_avoider.is_rerouting():
                self.line_follower.reset()
                self.transition(State.FOLLOWING)
                return

            self.uart.send(cmd_vector(max(10, vx + 20), vy, omega))
            self.line_follower.debug_vx = vx + 20
            self.line_follower.debug_vy = vy
            self.line_follower.debug_omega = omega
        else:
            self.line_follower.reset()
            self.transition(State.FOLLOWING)

    def _tick_patrol(self):
        """Autonomous wander with person detection and gesture recognition."""
        if not self.patrol_controller:
            self.transition(State.IDLE)
            return

        faces = []
        obstacles = []
        hands = []
        if self.person_detector and self._last_frame is not None:
            faces = self.person_detector.detect_faces(self._last_frame)
            self._last_faces = faces
            # EC1: Also detect hand gestures during patrol
            hands = self.person_detector.detect_hands(self._last_frame)
        if self.obstacle_detector and self._last_frame is not None:
            obstacles = self.obstacle_detector.detect(self._last_frame)
            self._last_obstacles = obstacles

        # EC1: React to gestures
        for hand in hands:
            gesture = self.person_detector.get_gesture(hand)
            if gesture == "open":  # open palm = stop
                self.uart.send(cmd_stop())
                if self.speaker:
                    self.speaker.say("stop")
                self.transition(State.IDLE)
                return
            elif gesture == "thumbs_up":  # thumbs up = come here
                self.transition(State.PERSON_APPROACH)
                return
            elif gesture == "peace":  # peace sign = take photo
                self._photo_taken = False
                self.transition(State.PHOTO)
                return
            elif gesture == "point":  # point = follow track
                self.line_follower.reset()
                self.transition(State.FOLLOWING)
                return

        # R4: Also check ultrasonic
        if self._check_ultrasonic_obstacle():
            self.uart.send(cmd_stop())
            return

        if self.patrol_controller.should_approach_person():
            self.transition(State.PERSON_APPROACH)
            return

        vx, vy, omega = self.patrol_controller.compute_wander(obstacles, faces)
        self.uart.send(cmd_vector(vx, vy, omega))
        self.line_follower.debug_vx = vx
        self.line_follower.debug_vy = vy
        self.line_follower.debug_omega = omega

    def _tick_person_approach(self):
        """Approach a detected person using face tracking."""
        if not self.person_detector or self._last_frame is None:
            self.transition(State.IDLE)
            return

        faces = self.person_detector.detect_faces(self._last_frame)
        self._last_faces = faces

        if not faces:
            self.uart.send(cmd_stop())
            self.transition(State.PATROL)
            return

        face = max(faces, key=lambda f: f["bbox"][2] * f["bbox"][3])
        cx, cy = face["center"]
        bw, bh = face["bbox"][2], face["bbox"][3]
        frame_w = self.config.vision.resolution[0]

        face_area = bw * bh
        target_area = 15000

        if face_area >= target_area:
            self.uart.send(cmd_stop())
            self.uart.send(cmd_buzzer(800, 200))
            print(">>> Person reached")
            if self.speaker:
                self.speaker.say("Hello! How may I help you?")
            self.transition(State.IDLE)
            return

        lateral_error = (cx - frame_w / 2) / (frame_w / 2)
        vx = max(15, min(50, int(50 * (1.0 - face_area / target_area))))
        omega = int(-lateral_error * 40)

        self.uart.send(cmd_vector(vx, 0, omega))
        self.line_follower.debug_vx = vx
        self.line_follower.debug_vy = 0
        self.line_follower.debug_omega = omega

    def _tick_dancing(self):
        """Execute a dance routine with timed moves."""
        if self._dance_start is None:
            self._dance_start = time.monotonic()

        elapsed = time.monotonic() - self._dance_start

        if elapsed >= self._dance_duration:
            self.uart.send(cmd_stop())
            self._dance_start = None
            self.transition(State.IDLE)
            return

        phase = int(elapsed / 0.5) % 6
        moves = [
            (0, 0, 60),     # spin right
            (30, 0, 0),     # forward
            (0, 0, -60),    # spin left
            (-30, 0, 0),    # backward
            (0, 40, 0),     # strafe right
            (0, -40, 0),    # strafe left
        ]
        vx, vy, omega = moves[phase]
        self.uart.send(cmd_vector(vx, vy, omega))
        self.line_follower.debug_vx = vx
        self.line_follower.debug_vy = vy
        self.line_follower.debug_omega = omega

        # Rainbow LEDs already set via transition()
        if self.leds and elapsed < 0.1:
            self.leds.rainbow_cycle(speed=0.03, duration=self._dance_duration)

    def _tick_photo(self):
        """Capture a photo from camera."""
        if self._photo_taken:
            self.transition(State.IDLE)
            return

        if self.camera and self.camera.is_available:
            frame = self.camera.read_frame()
            if frame is not None:
                try:
                    import cv2
                    filename = f"photo_{int(time.time())}.jpg"
                    cv2.imwrite(filename, frame)
                    print(f">>> Photo saved: {filename}")
                except Exception as e:
                    print(f">>> Photo save failed: {e}")
        else:
            print(">>> No camera available for photo")

        self._photo_taken = True
        self.uart.send(cmd_buzzer(1500, 100))  # R5: shutter sound
        if self.speaker:
            self.speaker.say("photo")

    def _tick_lost_reverse(self):
        """Continue line follower through lost-reverse recovery."""
        self._tick_following()

    def _tick_lost_pivot(self):
        """Continue line follower through lost-pivot recovery."""
        self._tick_following()

    def _tick_stopping(self):
        """Send stop command and return to IDLE."""
        self.uart.send(cmd_stop())
        self.line_follower.debug_vx = 0
        self.line_follower.debug_vy = 0
        self.line_follower.debug_omega = 0
        self.transition(State.IDLE)

    def _tick_sleeping(self):
        """Sleep state. Requires wake word ("Hello Sonny") to wake up again."""
        if self.voice_listener and self.voice_listener.is_wake_word_detected():
            if self.speaker:
                self.speaker.say("awake")
            if self.personality:
                self.personality.express_greeting()
            self.transition(State.LISTENING)

    # -- Main loop ----------------------------------------------------------

    def run(self):
        """Start the FSM and loop tick() at ~30 Hz until interrupted."""
        self.start()
        tick_interval = 1.0 / 30.0
        try:
            while self._running:
                t0 = time.monotonic()
                self.tick()
                elapsed = time.monotonic() - t0
                sleep_time = tick_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
        finally:
            self.stop()
