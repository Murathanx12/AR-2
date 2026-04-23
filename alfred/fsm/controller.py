"""Alfred V4 FSM controller — main dispatch loop coordinating all subsystems."""

import time
import logging

from alfred.config import CONFIG
from alfred.fsm.states import State, STATE_NAMES
from alfred.comms.uart import UARTBridge
from alfred.comms.protocol import (
    cmd_stop, cmd_vector, cmd_buzzer,
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

    def __init__(self, config=None, headless=False, no_voice=False, no_camera=False,
                 use_vision_ai=False, vision_ai_interval=5.0,
                 no_ultrasonic=False, no_yolo_obstacle=False,
                 enable_yolo=False, enable_person=False):
        self.config = config or CONFIG
        self.headless = headless
        self.no_voice = no_voice
        self.no_camera = no_camera
        self.use_vision_ai = use_vision_ai
        self.vision_ai_interval = vision_ai_interval
        # Runtime kill-switches. `no_ultrasonic` ignores HC-SR04 readings when
        # the sensor board is offline / noisy. `no_yolo_obstacle` still
        # silences the check even if YOLO is loaded. `enable_yolo` /
        # `enable_person` are the new defaults-off loading gates — vision
        # models are NOT imported unless explicitly requested. This is the
        # biggest FPS win: the Pi 5 was spending 50-100 ms/frame on YOLO
        # inference and ~15 ms on MediaPipe init+warmup on every detect call.
        # ArUco is the only vision that actually runs every tick.
        self.no_ultrasonic = no_ultrasonic
        self.no_yolo_obstacle = no_yolo_obstacle
        self.enable_yolo = enable_yolo
        self.enable_person = enable_person

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
            except Exception as e:
                print(f"[Init] Camera unavailable: {e}")
            try:
                from alfred.vision.aruco import ArucoDetector
                self.aruco_detector = ArucoDetector(
                    dict_name=self.config.vision.aruco_dict,
                )
            except Exception as e:
                print(f"[Init] ArUco unavailable: {e}")
            # Contour obstacle detector is cheap — keep it available as the
            # lightweight fallback path when camera-obstacle is enabled.
            try:
                from alfred.vision.obstacle import ObstacleDetector
                self.obstacle_detector = ObstacleDetector()
            except Exception as e:
                print(f"[Init] Obstacle detector unavailable: {e}")
            # MediaPipe person/face/gesture detection — opt-in. Loading it
            # warms up TensorFlow Lite models which take ~300 ms on Pi 5.
            if enable_person:
                try:
                    from alfred.vision.person import PersonDetector
                    self.person_detector = PersonDetector()
                    print("[Init] MediaPipe person detector ready (opt-in)")
                except Exception as e:
                    print(f"[Init] Person detector unavailable: {e}")

        # YOLO — opt-in only. Inference runs ~50-100 ms/frame on Pi 5 CPU,
        # which is the single biggest source of FPS drop when the FSM calls
        # `is_path_clear` or `get_obstacles` per tick. Ultrasonic is the
        # primary R4 sensor; YOLO is only useful when user explicitly asks.
        self.yolo_detector = None
        if enable_yolo and not no_camera:
            try:
                from alfred.vision.yolo_detector import YOLODetector
                self.yolo_detector = YOLODetector()
                if self.yolo_detector.is_available:
                    print("[Init] YOLO object detector ready (opt-in)")
                else:
                    self.yolo_detector = None
            except Exception:
                pass

        # Scene analyzer (OpenAI Vision — optional, off by default)
        self.scene_analyzer = None
        if use_vision_ai and not no_camera:
            try:
                from alfred.vision.scene_analyzer import SceneAnalyzer
                self.scene_analyzer = SceneAnalyzer(min_interval=vision_ai_interval)
                if self.scene_analyzer.is_available:
                    print(f"[Init] OpenAI Scene Analyzer ready (interval={vision_ai_interval}s)")
                else:
                    self.scene_analyzer = None
            except Exception:
                pass

        # Navigation subsystems
        self.aruco_approach = None
        self.obstacle_avoider = None
        self.patrol_controller = None

        try:
            from alfred.navigation.aruco_approach import ArucoApproach
            self.aruco_approach = ArucoApproach()
        except Exception as e:
            print(f"[Init] ArUco approach unavailable: {e}")
        try:
            from alfred.navigation.patrol import PatrolController
            self.patrol_controller = PatrolController()
        except Exception as e:
            print(f"[Init] Patrol unavailable: {e}")

        # Voice subsystems
        self.voice_listener = None
        self.intent_classifier = None
        self.speaker = None
        self.conversation = None

        if not no_voice:
            # Prefer the OpenAI Realtime streaming listener (WebSocket +
            # server-VAD + gpt-4o-mini-transcribe). No head-of-line blocking
            # during transcribe so "stop" is always heard. Falls back to
            # the batch VoiceListener if the SDK / key / network is missing.
            try:
                from alfred.voice.realtime_listener import RealtimeVoiceListener
                self.voice_listener = RealtimeVoiceListener(
                    wake_phrase=self.config.voice.wake_phrase,
                )
                print("[Init] Voice: Realtime API path")
            except Exception as e:
                print(f"[Init] Realtime unavailable ({e}) — batch fallback")
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
            # Link speaker to listener so mic mutes while robot talks
            if self.voice_listener and self.speaker:
                self.voice_listener.set_speaker(self.speaker)
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
                width=self.config.expression.eye_width,
                height=self.config.expression.eye_height,
            )
        except Exception:
            pass
        try:
            from alfred.expression.leds import LEDController
            self.leds = LEDController()
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

        # Arm servos (cosmetic)
        self.arms = None
        try:
            from alfred.expression.arms import ArmController
            self.arms = ArmController()
        except Exception:
            pass

        # GUI (created externally via set_gui)
        self.gui = None

        self.state = State.IDLE
        self._running = False
        self._previous_state = None  # for resuming after obstacle
        # Announcement dedup: state flips can cascade into back-to-back TTS,
        # which keeps the mic muted and swallows the user's next "stop".
        self._last_announced_state = None
        self._last_announced_time = 0.0
        # Hysteresis for ARUCO_APPROACH: require several consecutive lost-tag
        # frames before falling back to SEARCH. One dropped detection at 22fps
        # is not a lost marker.
        self._aruco_lost_frames = 0
        # 15 frames @ 14 fps ≈ 1 s. The earlier value of 5 (~350 ms) caused
        # APPR↔SRCH ping-pong whenever the robot rotated/strafed in the
        # stop band: one motion-blur frame + lose tag → SEARCH → re-find
        # → APPR. 1 s is long enough to absorb the manoeuvre, short enough
        # to recover quickly when the marker is genuinely gone.
        self.ARUCO_LOST_FRAMES_THRESHOLD = 15

        # Per-state context
        self._dance_start = None
        self._dance_duration = 10.0
        self._dance_proc = None
        self._photo_taken = False
        self._aruco_target_id = None  # None = follow any marker, int = specific ID
        self._aruco_announced_id = None  # last marker ID we've already spoken about
        self._aruco_arrived_announced = False
        self._aruco_hold_start = None
        self._last_aruco_pose = None
        self._last_frame = None
        self._last_faces = []
        self._last_obstacles = []
        # Cache one ArUco detection per tick — GUI reuses this instead of
        # running its own detect, saving ~40 ms per frame at 1080p.
        self._last_markers = []
        self._listen_timeout = None
        # Person-follow state
        self._person_smooth_cx = None
        self._person_smooth_bw = None
        self._person_lost_since = None
        self._person_greeted = False

        # Blocked state timing
        self._blocked_entry_time = None

        # Marker memory — keeps last-known bearing so search after a reroute
        # or brief occlusion spins the *right* way, not a blind sweep.
        self._aruco_last_cx = None
        self._aruco_last_size = None
        self._aruco_last_frame_w = None
        self._aruco_last_seen_time = None

        # Camera-based rerouting. Three-phase sub-FSM: rotate so the camera
        # faces the direction of motion, drive forward past the obstacle,
        # then rotate back toward the marker's last-known bearing. This is
        # strictly safer than pure mecanum strafe because the camera always
        # leads the motion — we can see what we're about to hit.
        self._reroute_start_time = None
        self._reroute_phase = None      # "turn_away" | "drive_around" | "turn_back"
        self._reroute_phase_start = None
        self._reroute_omega_sign = 0    # -1 = first rotate left, +1 = first rotate right
        self._reroute_clear_count = 0
        self._reroute_from = None       # state to return to once path clears
        self._reroute_us_clear_since = 0.0  # when turn_away first saw US clear

        # Ultrasonic-driven approach behaviour. `_us_slow_count` ticks while
        # the centre HC-SR04 is below `slow_cm`; once it exceeds `slow_debounce`,
        # the approach speed is halved. `_us_reroute_count` ticks while a real
        # obstacle (US distinctly closer than the camera-marker distance)
        # persists; once it exceeds `reroute_debounce`, we hop into REROUTING.
        # `_us_stop_count` ticks while US says we're in stop-zone range (≤
        # stop_cm with marker visible); once it exceeds `stop_debounce`, we
        # tell ArucoApproach we're in band even if camera-distance hasn't
        # crossed STOP_DIST_M yet — gives the user-requested ultrasonic stop.
        # All three counters reset to zero on the first tick the condition fails.
        self._us_slow_count = 0
        self._us_reroute_count = 0
        self._us_stop_count = 0

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
        logger.info(f"STATE {old_name} -> {new_name}")
        print(f"[FSM] {old_name} -> {new_name}")

        self._previous_state = self.state
        self.state = new_state
        self._blocked_entry_time = None

        # R5: Update LED color for new state
        self._update_led(new_state)

        # R5: TTS announcement for state transition — but dedup so that a
        # rapid APPR↔SRCH flicker doesn't spam TTS and mute the mic.
        announcement = STATE_ANNOUNCEMENTS.get(new_state)
        if announcement and self.speaker:
            now = time.monotonic()
            if (new_state != self._last_announced_state or
                    now - self._last_announced_time > 5.0):
                self.speaker.say(announcement)
                self._last_announced_state = new_state
                self._last_announced_time = now

        # EC5: Cosmetic arm animations
        if self.arms:
            self.arms.express_state(new_name)

    def _update_led(self, state):
        """Update LED state color for GUI display. NeoPixels are not installed."""
        pass

    def _check_ultrasonic_obstacle(self) -> bool:
        """Check any ultrasonic sensor for obstacles (R4).

        Returns True only if any sensor is connected AND obstacle within threshold.
        Returns False if no sensor data (distance == -1) or sensors disabled.

        When ultrasonic is physically disconnected, the ESP32 still reports values
        — dangling echo wires pick up noise and produce phantom short-range
        readings that oscillate FOLLOW ↔ BLOCKED. `--no-ultrasonic` disables it.
        """
        if self.no_ultrasonic:
            return False
        return self.uart.is_obstacle_detected(OBSTACLE_THRESHOLD_CM)

    def _get_obstacle_direction(self) -> str:
        """Return which ultrasonic sensor sees the closest obstacle.

        Returns 'left', 'center', 'right', or 'none'.
        """
        return self.uart.get_obstacle_direction(OBSTACLE_THRESHOLD_CM)

    def _check_camera_obstacle(self) -> bool:
        """Check camera-based obstacle detection using YOLO or contour fallback (R4).

        Returns True if obstacle detected. Returns False if no detector or
        disabled via `--no-yolo-obstacle`.
        """
        if self.no_yolo_obstacle:
            return False
        if self._last_frame is None:
            return False
        if self.yolo_detector:
            return not self.yolo_detector.is_path_clear(self._last_frame)
        if self.obstacle_detector:
            return not self.obstacle_detector.is_path_clear(self._last_frame)
        return False

    def _get_front_obstacles(self):
        """Helper — list biggest-first. Used by several REROUTING heuristics."""
        if self._last_frame is None:
            return []
        obstacles = []
        if self.yolo_detector:
            try:
                obstacles = self.yolo_detector.get_obstacles(self._last_frame)
            except Exception:
                obstacles = []
        if not obstacles and self.obstacle_detector:
            try:
                obstacles = self.obstacle_detector.detect(self._last_frame)
            except Exception:
                obstacles = []
        def _area(o):
            if "area" in o:
                return o["area"]
            _, _, bw, bh = o["bbox"]
            return bw * bh
        return sorted(obstacles, key=_area, reverse=True)

    def _front_obstacle_cx(self):
        """Return the x-pixel centre of the largest obstacle in front, or None.

        Used by REROUTING to decide which side to strafe.
        """
        obstacles = self._get_front_obstacles()
        if not obstacles:
            return None
        biggest = obstacles[0]
        if "center" in biggest:
            return float(biggest["center"][0])
        bx, _, bw, _ = biggest["bbox"]
        return bx + bw / 2.0

    def _choose_reroute_side(self):
        """Pick which side to pass the obstacle on.

        Returns -1 to pass on the **left** (rotate CCW, negative omega),
        +1 to pass on the **right** (rotate CW, positive omega).

        Three signals, combined in this priority order:
          1. Lateral clearance — for each side, how much empty horizontal
             space is between the obstacle and the frame edge (reduced by
             any secondary obstacle sitting in the "escape lane"). If one
             side has at least 1.5× the clearance of the other, that wins
             outright — we're not going to squeeze past a wall.
          2. Tag bearing memory — if `_aruco_last_cx` is fresh, passing on
             the same side as the tag is a shorter path back. Used as a
             tiebreaker when clearances are comparable.
          3. Geometric fallback — obstacle on right half → pass left,
             obstacle on left half → pass right (the simple mirror).
        """
        if self._last_frame is None:
            return -1
        obstacles = self._get_front_obstacles()
        if not obstacles:
            return -1

        h, w = self._last_frame.shape[:2]
        bx, by, bw, bh = obstacles[0]["bbox"]
        obs_cx = bx + bw / 2.0

        # Raw clearance: space between obstacle edge and frame edge.
        left_clearance = max(0.0, bx)
        right_clearance = max(0.0, w - (bx + bw))

        # Shrink the clearance on whichever side has a secondary obstacle
        # sitting in the escape lane. (Obstacle entirely to the left of the
        # main one → narrows the left-lane usable gap.)
        for o in obstacles[1:]:
            ox, _, ow, _ = o["bbox"]
            if ox + ow <= bx:           # whole thing is left of the main obstacle
                left_clearance = min(left_clearance, bx - (ox + ow))
            elif ox >= bx + bw:         # whole thing is right of the main
                right_clearance = min(right_clearance, ox - (bx + bw))

        # Tag-bearing preference (only if memory is recent — <10 s old).
        tag_hint = 0
        if (self._aruco_last_cx is not None and self._aruco_last_frame_w and
                self._aruco_last_seen_time is not None and
                time.monotonic() - self._aruco_last_seen_time < 10.0):
            tag_frac = self._aruco_last_cx / self._aruco_last_frame_w
            if tag_frac < 0.45:
                tag_hint = -1
            elif tag_frac > 0.55:
                tag_hint = +1

        # Decision: clearance dominates if one side is clearly better.
        if left_clearance > right_clearance * 1.5:
            return -1
        if right_clearance > left_clearance * 1.5:
            return +1

        # Close call → use the tag-side tiebreaker.
        if tag_hint != 0:
            return tag_hint

        # No strong signal either way — fall back to the original mirror.
        return -1 if obs_cx > w / 2 else +1

    def _obstacle_is_close(self):
        """Proximity estimate without depth sensors — is the obstacle close
        enough that we should stop + rotate, or far enough to curve around?

        Three independent cues, any one of which flags "close":
          1. Ultrasonic < 50 cm (if sensor wired; most reliable when available).
          2. Obstacle bbox bottom > 82 % of frame height (ground-plane heuristic —
             a closer object's bottom sits lower in the image).
          3. Obstacle bbox area > 18 % of frame area (large visual footprint).
        """
        if self._last_frame is None:
            return True  # safe default: assume close if we can't tell

        # Ultrasonic is the most trustworthy distance cue. Only use it if
        # the sensor is actually returning a reading (dist > 0).
        if self.uart:
            dist_cm = self.uart.get_distance()
            if 0 < dist_cm < 50:
                return True

        obstacles = self._get_front_obstacles()
        if not obstacles:
            return False  # nothing visible — treat as far

        h, w = self._last_frame.shape[:2]
        frame_area = float(w * h)
        for obs in obstacles[:3]:  # only the three biggest matter
            bx, by, bw, bh = obs["bbox"]
            bbox_bottom = by + bh
            if bbox_bottom > h * 0.82:
                return True
            if (bw * bh) > frame_area * 0.18:
                return True
        return False

    def _remember_marker(self, marker, frame):
        """Cache the marker's current cx/size so a later search can spin
        toward its last-known bearing instead of sweeping blindly."""
        self._aruco_last_cx = marker["center"][0]
        self._aruco_last_size = marker["size"]
        self._aruco_last_frame_w = frame.shape[1]
        self._aruco_last_seen_time = time.monotonic()

    def _reset_reroute(self):
        self._reroute_start_time = None
        self._reroute_phase = None
        self._reroute_phase_start = None
        self._reroute_omega_sign = 0
        self._reroute_clear_count = 0
        self._reroute_from = None
        self._reroute_us_clear_since = 0.0

    def _reroute_path_clear(self) -> bool:
        """Is the forward path clear during a reroute manoeuvre?

        Used by the `curve` and `drive_around` phases to decide whether to
        commit to forward motion. Combines the camera contour/YOLO check
        with the centre ultrasonic so a known-bad contour fallback (which
        false-positives on shadows / the marker stand) doesn't stall the
        manoeuvre when the sensor confirms there's nothing in front.

        Truth table when both signals are available:
            US clear (>slow_cm or no echo) → CLEAR (overrides camera flicker)
            US silent / not wired          → trust camera
            US close + camera clear        → blocked (trust the sensor)
            US close + camera blocked      → blocked
        """
        cam_blocked = self._check_camera_obstacle()
        if self.no_ultrasonic:
            return not cam_blocked
        us_cm = self.uart.get_distance()
        us_cfg = self.config.ultrasonic
        # Negative dist = no echo (nothing within range = clear).
        us_clear = us_cm < 0 or us_cm > us_cfg.slow_cm
        if us_clear:
            return True
        return not cam_blocked

    def tick(self):
        """Run one FSM cycle: read sensors, dispatch state handler, update expression."""
        # Read camera frame (shared across states)
        if self.camera and self.camera.is_available:
            self._last_frame = self.camera.read_frame()
            # Run ArUco detection exactly once per tick — the result is cached
            # for any state handler + the GUI.
            if self._last_frame is not None and self.aruco_detector:
                try:
                    self._last_markers = self.aruco_detector.detect(self._last_frame)
                except Exception:
                    self._last_markers = []
            else:
                self._last_markers = []
            if self.gui and self._last_frame is not None:
                self.gui.set_camera_frame(self._last_frame)

        # Periodic AI scene analysis during active navigation
        if self.scene_analyzer and self._last_frame is not None:
            if self.state in (State.PATROL, State.ARUCO_SEARCH, State.PERSON_APPROACH):
                self.scene_analyzer.analyze_async(self._last_frame)

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
        """Handle a recognised voice command. Simple: match or don't."""
        if not self.intent_classifier:
            return

        # Special signal from listener: bare "hello" heard
        if text == "__confirm_wake__":
            # Just wake up directly — don't ask confirmation
            return

        # Fast path: any of these tokens anywhere in the heard utterance
        # snaps to stop intent and skips the GPT-4o-mini round trip
        # (~300 ms instead of ~800 ms). Substring match — so "Sonny stop",
        # "stop the robot", "please stop now", "halt!", "freeze" all hit.
        # The cost of a false positive is just an unnecessary stop, which
        # the user can always override with the next command. The cost of
        # a missed stop is collisions, so we lean permissive here.
        stripped = text.strip().lower().rstrip(".!,?")
        STOP_TOKENS = ("stop", "halt", "freeze", "abort", "cancel", "wait")
        words = stripped.split()
        if any(tok in words for tok in STOP_TOKENS):
            intent, confidence = "stop", 1.0
        else:
            intent, confidence = self.intent_classifier.classify(text)
        logger.info(f"VOICE '{text}' -> intent={intent} conf={confidence:.0%}")
        print(f"[Voice] '{text}' -> {intent} ({confidence:.0%})")

        if self.gui:
            self.gui.set_voice_input(text, intent, confidence)

        # STOP always works immediately from any state.
        # Kills active TTS, drops queued utterances, and clears nav state so
        # pending announcements ("Found marker X…") don't keep playing.
        if intent == "stop":
            self.uart.send(cmd_stop())
            self.line_follower.debug_vx = 0
            self.line_follower.debug_vy = 0
            self.line_follower.debug_omega = 0
            self._aruco_target_id = None           # drop any marker chase
            self._aruco_announced_id = None
            self._aruco_lost_frames = 0
            self._aruco_arrived_announced = False
            self._reset_reroute()
            self._us_slow_count = 0
            self._us_reroute_count = 0
            self._us_stop_count = 0
            if self.aruco_approach:
                self.aruco_approach.reset()           # clears 3-s stop debounce
            if self.speaker:
                self.speaker.stop()
                self.speaker.say("stop")
            if self.gui:
                self.gui.set_voice_output("Stopping.")
            # Reset announcement dedup so "stop" announcement itself is heard.
            self._last_announced_state = None
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

        # Explain the current task — speak a natural-language description of
        # the FSM state + context (marker id, reroute phase, etc.). Does not
        # change state. Also shows a banner on the demo face for 5 seconds.
        if intent == "explain_task":
            desc = self._describe_current_task()
            print(f"[ExplainTask] {desc}")
            if self.speaker:
                self.speaker.say(desc)
            if self.gui:
                self.gui.set_voice_output(desc)
                if hasattr(self.gui, "show_task_banner"):
                    self.gui.show_task_banner(desc)
            return

        # Show photo gallery — announce URL, stay in current state
        if intent == "show_photos":
            import socket
            try:
                ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                ip = "the Pi"
            url = f"http://{ip}:8080/photos"
            msg = f"Opening the photo gallery at {url}"
            if self.speaker:
                self.speaker.say("Here are the pictures I took.")
            if self.gui:
                self.gui.set_voice_output(msg)
            print(f"[Gallery] {msg}")
            return

        # EC3: Chat — route to conversation engine
        if intent == "chat":
            self._route_to_conversation(text)
            return

        # Map to state
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
        if target:
            # Low confidence — ask to confirm instead of blindly executing
            if confidence < 0.7:
                confirmations_ask = {
                    "follow_track": "Did you say follow the track? Say yes or repeat your command.",
                    "go_to_aruco":  "Did you say go to a marker? Say yes or repeat your command.",
                    "dance":        "Did you want me to dance? Say yes or say it again.",
                    "take_photo":   "Take a photo? Say yes or repeat.",
                    "come_here":    "Did you say come here? Say yes or try again.",
                    "patrol":       "Start patrolling? Say yes or say it again.",
                    "search":       "Search for a marker? Say yes or try again.",
                }
                msg = confirmations_ask.get(intent, "I'm not sure I understood. Could you say that again?")
                if self.speaker:
                    self.speaker.say(msg)
                if self.gui:
                    self.gui.set_voice_output(msg)
                return

            confirmations = {
                "follow_track": "Following the track.",
                "dance":        "Time to dance!",
                "take_photo":   "Say cheese!",
                "come_here":    "Coming to you.",
                "patrol":       "Starting patrol.",
                "search":       "Searching for the marker.",
            }
            if intent in ("go_to_aruco", "search"):
                marker_id = getattr(self.intent_classifier, 'last_marker_id', None)
                if marker_id is None:
                    marker_id = self.intent_classifier.extract_marker_id(text)
                if marker_id is not None:
                    msg = f"Searching for marker {marker_id}."
                else:
                    msg = "Searching for any marker."
            else:
                msg = confirmations.get(intent, "Got it.")
            if self.speaker:
                self.speaker.say(msg)
            if self.gui:
                self.gui.set_voice_output(msg)

            if target == State.FOLLOWING:
                self.line_follower.reset()
            elif target == State.DANCING:
                self._dance_start = time.monotonic()
            elif target == State.PHOTO:
                self._photo_taken = False
            elif target == State.ARUCO_SEARCH:
                marker_id = getattr(self.intent_classifier, 'last_marker_id', None)
                if marker_id is None:
                    marker_id = self.intent_classifier.extract_marker_id(text)
                if marker_id is not None:
                    self._aruco_target_id = marker_id
                    print(f"[ArUco] Target set to marker ID {marker_id}")
                else:
                    self._aruco_target_id = None
                    print(f"[ArUco] Following any visible marker")
                self._aruco_announced_id = None  # fresh command, re-announce on acquire
                self._aruco_arrived_announced = False
                self._aruco_hold_start = None
                self._aruco_lost_frames = 0
                # Clear stale bearing memory from a previous target.
                self._aruco_last_cx = None
                self._aruco_last_size = None
                self._aruco_last_frame_w = None
                self._aruco_last_seen_time = None
                self._reset_reroute()
                self._us_slow_count = 0
                self._us_reroute_count = 0
                self._us_stop_count = 0
                if self.aruco_approach:
                    self.aruco_approach.reset()
            elif target == State.PERSON_APPROACH:
                self._person_smooth_cx = None
                self._person_smooth_bw = None
                self._person_lost_since = None
                self._person_greeted = False
            self.transition(target)

        elif intent in ("confirm", "cancel"):
            pass  # ignore stray yes/no

        elif intent == "unknown":
            self._route_to_conversation(text)

    def _describe_current_task(self):
        """Plain-English sentence describing what Sonny is doing right now.

        Used by the `explain_task` voice intent — when the user asks
        "what are you doing" the robot speaks this. Includes context
        that isn't just the state name (target marker id, obstacle
        status, last voice command, reroute phase).
        """
        st = self.state

        if st == State.IDLE:
            return "I am standing by and waiting for your next command."

        if st == State.LISTENING:
            return "I am listening for a voice command."

        if st == State.FOLLOWING:
            return "I am following the black line on the floor."

        if st == State.ENDPOINT:
            return "I have reached the end of the track."

        if st == State.PARKING:
            return "I am parking at the delivery zone."

        if st == State.ARUCO_SEARCH:
            target = getattr(self, "_aruco_target_id", None)
            if target is not None:
                return f"I am searching for ArUco marker number {target}."
            return "I am searching for any ArUco marker in view."

        if st == State.ARUCO_APPROACH:
            target = getattr(self, "_aruco_target_id", None)
            if target is not None:
                return (f"I have found marker {target} and I am "
                        f"approaching it. I will stop about twenty "
                        f"centimetres in front.")
            return ("I have found a marker and I am approaching it. "
                    "I will stop about thirty centimetres in front.")

        if st == State.BLOCKED:
            return ("There is an obstacle in front of me. I am waiting "
                    "for the path to clear before continuing.")

        if st == State.REROUTING:
            phase = getattr(self, "_reroute_phase", None)
            if phase == "turn_away":
                return "The path is blocked. I am rotating to face away from the obstacle."
            if phase == "drive_around":
                return "The path is blocked. I am driving around the obstacle."
            if phase == "turn_back":
                return "I am turning back to look for my target marker."
            return "The path is blocked, so I am finding a way around the obstacle."

        if st == State.PATROL:
            return "I am patrolling the area. I will approach people or gestures if I see them."

        if st == State.PERSON_APPROACH:
            return "I can see a person. I am approaching them."

        if st == State.DANCING:
            return "I am dancing!"

        if st == State.PHOTO:
            return "I am taking a photo."

        if st == State.LOST_REVERSE:
            return "I lost the line. I am reversing to recover it."

        if st == State.LOST_PIVOT:
            return "I lost the line. I am pivoting in place to find it again."

        if st == State.STOPPING:
            return "I am stopping all movement."

        if st == State.SLEEPING:
            return "I am sleeping. Say hello Sonny to wake me up."

        return "I am not sure what I am doing right now. Please give me a command."

    def _route_to_conversation(self, text):
        """Route text to conversation engine, or ask to rephrase if unavailable."""
        if self.conversation and self.conversation.is_available:
            self.conversation.handle(text)
            if self.gui:
                self.gui.set_voice_output(f"Chatting: {text}")
        else:
            msg = "I'm not sure what you'd like. Could you say that again? Try follow track, go to marker, or dance."
            if self.speaker:
                self.speaker.say(msg)
            if self.gui:
                self.gui.set_voice_output(msg)

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
        """Scan for ArUco markers by rotating slowly.

        If target_id is set (e.g. "go to marker 42"): only approach that ID.
        If target_id is None (e.g. "go to qr code"): approach nearest/largest marker.
        """
        if self._check_ultrasonic_obstacle():
            self.transition(State.BLOCKED)
            return

        if self.aruco_detector and self._last_frame is not None:
            markers = self._last_markers  # cached this tick — no re-detect
            if markers:
                target = None

                if self._aruco_target_id is not None:
                    # Looking for specific ID
                    for m in markers:
                        if m["id"] == self._aruco_target_id:
                            target = m
                            break
                    if target is None:
                        seen = [m["id"] for m in markers]
                        print(f"[ArUco] See {seen}, want {self._aruco_target_id}")
                else:
                    # No specific target — approach the largest (closest) marker
                    target = max(markers, key=lambda m: m["size"])
                    self._aruco_target_id = target["id"]

                if target:
                    print(f"[ArUco] Found marker {target['id']}! size={target['size']:.0f}px")
                    # Only announce the first time we acquire this specific marker,
                    # not every time the tracker re-acquires after brief occlusion.
                    already = getattr(self, "_aruco_announced_id", None)
                    if self.speaker and already != target["id"]:
                        self.speaker.say(f"Found marker {target['id']}. Approaching.")
                        self._aruco_announced_id = target["id"]
                    self._remember_marker(target, self._last_frame)
                    self.transition(State.ARUCO_APPROACH)
                    return

        # Direction-biased search. If we've seen the marker recently, spin
        # back toward its last-known bearing rather than the default (right).
        # Previous sign discipline: omega > 0 = spin right (CW).
        omega = 8
        if (self._aruco_last_cx is not None and self._aruco_last_frame_w and
                self._aruco_last_seen_time is not None and
                time.monotonic() - self._aruco_last_seen_time < 10.0):
            if self._aruco_last_cx < self._aruco_last_frame_w / 2:
                omega = -8  # marker was on my left — rotate left to re-acquire

        self.uart.send(cmd_vector(0, 0, omega))
        self.line_follower.debug_vx = 0
        self.line_follower.debug_vy = 0
        self.line_follower.debug_omega = omega

    def _tick_aruco_approach(self):
        """Drive toward detected ArUco marker — center first, then approach, then hold."""
        if not self.aruco_detector or not self.aruco_approach or self._last_frame is None:
            self.transition(State.IDLE)
            return

        markers = self._last_markers  # cached this tick

        # Find target marker (or any marker if target_id is None)
        target_marker = None
        if self._aruco_target_id is not None:
            for m in markers:
                if m["id"] == self._aruco_target_id:
                    target_marker = m
                    break
        elif markers:
            target_marker = max(markers, key=lambda m: m["size"])
            self._aruco_target_id = target_marker["id"]

        # === Ultrasonic-driven obstacle handling (debounced) ==================
        # The centre HC-SR04 (TRIG=GPIO8/ECHO=GPIO9, validated 2026-04-23) gives
        # us a depth cue the camera can't: it sees objects between us and the
        # marker. Two debounced behaviours:
        #   (1) reroute_cm  — sustained reading distinctly closer than the
        #                     camera-estimated marker distance → REROUTING.
        #                     Margin guards against treating the marker stand
        #                     itself as an obstacle.
        #   (2) slow_cm     — sustained reading just close-ish → halve forward
        #                     speed during the rest of this tick.
        # Both counters reset on the first tick the condition fails, so a
        # stray short read doesn't flick the FSM. They're zeroed again whenever
        # a fresh "go to marker" command sets up the approach.
        us_cfg = self.config.ultrasonic
        us_cm = self.uart.get_distance() if not self.no_ultrasonic else -1.0
        h_frame, w_frame = self._last_frame.shape[:2]
        marker_cm = -1.0
        if target_marker is not None and self.aruco_approach is not None:
            marker_cm = self.aruco_approach._distance_m(
                target_marker["size"], w_frame
            ) * 100.0

        # Reroute / BLOCKED only when we've fully settled at the marker
        # (`_holding=True`). The earlier version also suppressed during
        # the 3-s arrival debounce, which made the FSM ignore a real
        # obstacle that appeared while we were trying to confirm arrival
        # (observed 2026-04-23 ~19:59 — robot waited for user to move
        # the obstacle, then rammed it). The wider 20 cm reroute_margin
        # now keeps the marker stand from false-positiving even during
        # debounce, so this guard only needs to fire post-arrival.
        already_arrived = bool(
            self.aruco_approach and self.aruco_approach.is_holding()
        )
        # NOTE (2026-04-23 ~20:15): in-approach reroute is DISABLED when
        # the target marker is visible. The user observed the robot
        # rotating away from the marker as it got close, when really we
        # want it to centre on the QR + slow + stop based on US. With
        # target visible we trust the camera (centring + arrival) and
        # the ultrasonic slow/stop zones below. Reroute can still fire
        # via the lost-marker branch (further down) if the marker is
        # genuinely hidden by a closer obstacle.
        self._us_reroute_count = 0

        near_slow = (
            not self.no_ultrasonic
            and 0 < us_cm < us_cfg.slow_cm
        )
        if near_slow:
            self._us_slow_count += 1
        else:
            self._us_slow_count = 0
        slow_now = self._us_slow_count >= us_cfg.slow_debounce

        # US-confirmed stop zone (parallel to camera STOP_DIST_M). Triggers
        # when US <= stop_cm AND we still see the marker — that pair means
        # we've physically reached the marker, even if camera distance is a
        # few cm above its 40 cm threshold (which it can be at 1080p
        # because pixel-size jitter is ±2-3 cm).
        us_close_to_marker = (
            not self.no_ultrasonic
            and target_marker is not None
            and 0 < us_cm <= us_cfg.stop_cm
        )
        if us_close_to_marker:
            self._us_stop_count += 1
        else:
            self._us_stop_count = 0
        us_in_stop_zone = self._us_stop_count >= us_cfg.stop_debounce

        # ======================================================================
        # Ultrasonic emergency: < threshold_cm (default 20). With target
        # visible this is the safety net — just halt forward motion this
        # tick. The camera 3-s debounce is the authoritative arrival
        # mechanism (per the user spec, stops camera-driven at 40 cm), so we
        # do NOT auto-flip _holding here — that would bypass the debounce
        # and announce arrival on a single noisy frame. Without target it's
        # a hard BLOCKED. Sits AFTER the reroute check so a real obstacle
        # gets a chance to trigger reroute first.
        if self._check_ultrasonic_obstacle():
            # US < threshold (default 20 cm). Halt and stay in APPROACH if
            # ANY of these are true:
            #   * target visible right now (we're at it)
            #   * already arrived (hold-mode latched or in 3-s debounce)
            #   * marker seen recently (within ARUCO_LOST_FRAMES_THRESHOLD)
            #     — motion blur during diagonal centring drops a few
            #     frames, but at < 20 cm we're at the tag, not in front
            #     of an obstacle. Without this case, the FSM kicks to
            #     BLOCKED whenever fast strafe causes a single dropped
            #     detection (observed 19:58 on 2026-04-23).
            if (target_marker is not None
                    or already_arrived
                    or self._aruco_lost_frames < self.ARUCO_LOST_FRAMES_THRESHOLD):
                self.uart.send(cmd_stop())
                return
            self.transition(State.BLOCKED)
            return

        # NOTE: no camera-obstacle check during approach. Ultrasonic is the
        # primary R4 sensor now; the contour fallback (which runs when YOLO
        # is off, the default) false-positives on the marker stand, the
        # tag's border, and shadows, which causes REROUTE↔BLOCKED flip-flop
        # storms that muted the mic via rapid-fire TTS. If you need reroute
        # during approach, re-enable with --enable-yolo (real obstacle
        # detection) and uncomment the branch below.

        if target_marker is None:
            # Hysteresis — a single lost detection isn't a lost marker.
            # Drop-frames happen all the time at 20-25 fps from motion blur,
            # partial-occlusion, or the tag grazing a frame edge. Only fall
            # back to SEARCH after several consecutive losses, otherwise we
            # thrash and spam TTS announcements (which mute the mic).
            self._aruco_lost_frames += 1
            if self._aruco_lost_frames < self.ARUCO_LOST_FRAMES_THRESHOLD:
                # Coast straight at the last-known command for one more tick.
                vx = self.line_follower.debug_vx
                vy = self.line_follower.debug_vy
                omega = self.line_follower.debug_omega
                self.uart.send(cmd_vector(int(vx), int(vy), int(omega)))
                return
            if markers:
                # See markers but not our target
                seen = [m["id"] for m in markers]
                print(f"[ArUco] See {seen}, want {self._aruco_target_id}")
            # Genuinely lost. Three cases:
            #   1. Lost AND US is in the stop zone (≤ stop_cm = 40 cm) →
            #      we're physically AT the marker, the detection just
            #      blurred. Halt and let the next frame reacquire — do
            #      NOT sidestep, that's what made the robot turn 90° the
            #      moment it got close (observed 2026-04-23 ~20:14).
            #   2. Lost AND US shows an obstacle further out
            #      (stop_cm < US < reroute_cm) → tag is hidden behind
            #      something → REROUTING sidestep.
            #   3. Lost with line of sight clear → ARUCO_SEARCH with
            #      bearing-biased spin.
            self._aruco_lost_frames = 0
            us_in_stop = (
                not self.no_ultrasonic
                and 0 < us_cm <= us_cfg.stop_cm
            )
            if us_in_stop:
                print(f"[ArUco] Lost marker but US={us_cm:.0f}cm (≤ stop) — halting, marker is right here")
                self.uart.send(cmd_stop())
                return
            us_blocked_far = (
                not self.no_ultrasonic
                and not already_arrived
                and us_cfg.stop_cm < us_cm < us_cfg.reroute_cm
            )
            if us_blocked_far:
                print(f"[ArUco] Lost marker AND US={us_cm:.0f}cm — sidestepping via REROUTING")
                if self.speaker:
                    self.speaker.say("I lost the marker behind something. Stepping aside.")
                self._us_reroute_count = 0
                self._us_slow_count = 0
                self._reroute_from = State.ARUCO_APPROACH
                self.uart.send(cmd_stop())
                self.transition(State.REROUTING)
                return
            self.transition(State.ARUCO_SEARCH)
            return

        # Marker detected — reset lost counter.
        self._aruco_lost_frames = 0

        # Remember where/how big the marker is so later search/reroute can
        # recover without a blind spin.
        self._remember_marker(target_marker, self._last_frame)

        # Visual approach (reuse the frame size we already computed above).
        # Pass `us_in_stop_zone` so the camera-driven 3 s arrival debounce
        # also honours the centre ultrasonic — whichever sensor reports we
        # are at the marker first wins the stop.
        result = self.aruco_approach.compute_visual_approach(
            target_marker, w_frame, h_frame,
            us_in_stop_zone=us_in_stop_zone,
        )

        vx, vy, omega = result

        # Combined camera + ultrasonic forward-speed governor. Whichever
        # sensor reports "closer" wins, so a camera-distance over-estimate
        # can't override a US warning. Concretely:
        #   * camera-derived vx already comes from compute_visual_approach
        #   * us-derived vx scales linearly: vx_us = us_cm / slow_cm * 45
        #     (45 = the top end of `_forward_speed`)
        #   * use the SMALLER of the two; floor at 10 so wheels still turn.
        # This is what stops the robot from ramming the marker when camera
        # distance momentarily over-estimates due to motion blur.
        if vx > 0 and not self.no_ultrasonic and us_cm > 0:
            us_scale = max(0.20, min(1.0, us_cm / us_cfg.slow_cm))
            vx_us = max(int(45 * us_scale), 10)
            if vx_us < vx:
                if slow_now:
                    print(f"[ArUco] US slow: us={us_cm:.0f}cm, vx {vx}->{vx_us}")
                vx = vx_us

        # Announce arrival once when hold-mode first engages
        if self.aruco_approach.is_holding() and not self._aruco_arrived_announced:
            self._aruco_arrived_announced = True
            self._aruco_hold_start = time.monotonic()
            self.uart.send(cmd_buzzer(1200, 300))
            print(f">>> Holding at ArUco marker {self._aruco_target_id}")
            if self.speaker:
                self.speaker.say("I have arrived at the marker. Your delivery is ready.")

        self.uart.send(cmd_vector(int(vx), int(vy), int(omega)))
        self.line_follower.debug_vx = int(vx)
        self.line_follower.debug_vy = int(vy)
        self.line_follower.debug_omega = int(omega)

    def _tick_blocked(self):
        """Stop and wait for obstacle to clear (R4).

        Checks both ultrasonic AND camera before resuming. Minimum 1s dwell
        so we don't flicker BLOCKED<->APPROACH on a single noisy frame.
        """
        self.uart.send(cmd_stop())
        self.line_follower.debug_vx = 0
        self.line_follower.debug_vy = 0
        self.line_follower.debug_omega = 0

        now = time.monotonic()
        if self._blocked_entry_time is None:
            self._blocked_entry_time = now

        # Minimum 1s in BLOCKED to avoid flicker
        if now - self._blocked_entry_time < 1.0:
            return

        ultrasonic_clear = not self._check_ultrasonic_obstacle()
        camera_clear = not self._check_camera_obstacle()

        if ultrasonic_clear and camera_clear:
            self._blocked_entry_time = None
            if self.speaker:
                self.speaker.say("Path clear. Resuming.")
            if self._previous_state in (State.FOLLOWING, State.ENDPOINT, State.PARKING,
                                         State.LOST_REVERSE, State.LOST_PIVOT):
                self.line_follower.reset()
                self.transition(State.FOLLOWING)
            elif self._previous_state == State.ARUCO_APPROACH:
                self.transition(State.ARUCO_APPROACH)
            elif self._previous_state == State.ARUCO_SEARCH:
                self.transition(State.ARUCO_SEARCH)
            elif self._previous_state == State.REROUTING:
                self.transition(State.REROUTING)
            else:
                self.transition(State.IDLE)

    def _tick_rerouting(self):
        """Hybrid obstacle-avoidance manoeuvre — curves smoothly if the
        obstacle is still far, falls back to rotate-drive-rotate if close.

        On first tick, `_obstacle_is_close` picks between:

          curve        Smooth arc around the obstacle: vx=22 forward, omega
                       proportional to turn direction, small vy strafe. Camera
                       stays roughly forward, so the tag often remains in
                       peripheral view. If distance closes mid-curve the
                       phase auto-switches to turn_away for safety.

          turn_away    Rotate in place until the obstacle is at the frame edge.
          drive_around Drive forward (camera leads); exit on clear path +
                       minimum drive time, or per-phase timeout.
          turn_back    Rotate back looking for the tag; exit on acquisition,
                       else hand off to ARUCO_SEARCH with bearing-biased spin.

        Marker memory keeps updating through every phase so a brief glimpse
        of the tag refines the bearing used by the fallback search.
        """
        if self._last_frame is None:
            self.uart.send(cmd_stop())
            return

        now = time.monotonic()
        fw = self._last_frame.shape[1]

        # First-tick setup: pick rotation direction + curve-vs-rotate mode.
        if self._reroute_start_time is None:
            self._reroute_start_time = now
            self._reroute_phase_start = now
            self._reroute_clear_count = 0
            obs_cx = self._front_obstacle_cx()
            if obs_cx is None:
                # Nothing in view to avoid — bail straight back to approach.
                self._reset_reroute()
                self.transition(self._reroute_from or State.ARUCO_APPROACH)
                return
            # Direction convention throughout REROUTING:
            #   -1 = pass the obstacle on the LEFT (rotate CCW)
            #   +1 = pass the obstacle on the RIGHT (rotate CW)
            # _choose_reroute_side weighs lateral clearance first, then tag
            # bearing memory, then a default geometric mirror — so the robot
            # favours the side with more room, and uses the shorter path
            # back to the tag as a tiebreaker.
            self._reroute_omega_sign = self._choose_reroute_side()
            side = "left" if self._reroute_omega_sign < 0 else "right"

            # Decide avoidance mode based on how close the obstacle is.
            if self._obstacle_is_close():
                self._reroute_phase = "turn_away"
                print(f"[Reroute] Obstacle close (cx={obs_cx:.0f}) — stopping and rotating to go {side}")
                if self.speaker:
                    self.speaker.say(f"Obstacle close. Going around to the {side}.")
            else:
                self._reroute_phase = "curve"
                print(f"[Reroute] Obstacle far (cx={obs_cx:.0f}) — smooth curve around to the {side}")
                if self.speaker:
                    self.speaker.say(f"Curving around to the {side}.")

        # Ultrasonic always trumps camera. Close-range emergency → BLOCKED.
        if self._check_ultrasonic_obstacle():
            self.uart.send(cmd_stop())
            self._reset_reroute()
            self.transition(State.BLOCKED)
            return

        # Overall timeout: bail out rather than circle forever.
        if now - self._reroute_start_time > 8.0:
            print("[Reroute] Overall timeout — giving up.")
            if self.speaker:
                self.speaker.say("I cannot find a way around. Stopping.")
            self.uart.send(cmd_stop())
            self._reset_reroute()
            self.transition(State.IDLE)
            return

        # Keep marker memory fresh in every phase (cached this tick).
        if self.aruco_detector:
            markers = self._last_markers
            if markers:
                tgt = None
                if self._aruco_target_id is not None:
                    for m in markers:
                        if m["id"] == self._aruco_target_id:
                            tgt = m
                            break
                else:
                    tgt = max(markers, key=lambda m: m["size"])
                if tgt:
                    self._remember_marker(tgt, self._last_frame)

        phase_elapsed = now - self._reroute_phase_start

        # ===== Optional Phase 0: smooth curve (only when obstacle was far) =====
        if self._reroute_phase == "curve":
            # Continuous safety check: if the obstacle closed the distance
            # (we got too close to curve comfortably), abort to rotate-drive.
            if self._obstacle_is_close():
                print("[Reroute] Obstacle closed during curve — bailing to rotate.")
                if self.speaker:
                    self.speaker.say("Too close — stopping to turn.")
                self.uart.send(cmd_stop())
                self._reroute_phase = "turn_away"
                self._reroute_phase_start = now
                self._reroute_clear_count = 0
                return

            # Path-clear check. Camera contour can flicker on shadows / the
            # tag border, which used to stall the arc. Ultrasonic > slow_cm
            # (or no echo at all) is a reliable "nothing in front" cue and
            # short-circuits the camera if it disagrees.
            if self._reroute_path_clear():
                self._reroute_clear_count += 1
                # Minimum curve time 0.5 s + 5 clear frames means we committed
                # to the arc before exiting.
                if self._reroute_clear_count >= 5 and phase_elapsed > 0.5:
                    # If the tag is already visible after the curve, resume
                    # immediately; otherwise let ARUCO_APPROACH fall through
                    # to bearing-biased ARUCO_SEARCH.
                    print("[Reroute] Curve cleared — resuming approach.")
                    if self.speaker:
                        self.speaker.say("Path clear.")
                    self._reset_reroute()
                    self.transition(State.ARUCO_APPROACH)
                    return
            else:
                self._reroute_clear_count = 0

            # Per-phase timeout — if the curve didn't finish in 3.5 s it's
            # probably not the right manoeuvre. Switch to the discrete
            # rotate-drive-rotate. Keep the direction we chose.
            if phase_elapsed > 3.5:
                print("[Reroute] Curve timeout — falling back to rotate-drive.")
                self._reroute_phase = "turn_away"
                self._reroute_phase_start = now
                self._reroute_clear_count = 0
                return

            # Arc: forward + rotate away. omega_sign < 0 curves the robot
            # left (CCW), positive curves it right (CW). Small vy adds a
            # gentle mecanum strafe in the same direction, widening the arc.
            vx = 22
            omega = self._reroute_omega_sign * 12
            vy = self._reroute_omega_sign * 8
            self.uart.send(cmd_vector(vx, vy, omega))
            self.line_follower.debug_vx = vx
            self.line_follower.debug_vy = vy
            self.line_follower.debug_omega = omega
            return

        # ===== Phase 1: turn in place until ultrasonic confirms clear =====
        # Per user spec: rotate until the centre US no longer sees the
        # obstacle (us > slow_cm or no echo), then continue rotating an
        # extra 0.1 s so the obstacle is definitely past the cone, then
        # commit to drive_around. Camera-bbox-edge fallback kept as a
        # safety net because the US cone is narrow (~15°) — if the
        # obstacle is wider than the cone, US clears too soon.
        if self._reroute_phase == "turn_away":
            us_cm_now = self.uart.get_distance() if not self.no_ultrasonic else -1.0
            us_clear = (
                self.no_ultrasonic
                or us_cm_now < 0
                or us_cm_now > self.config.ultrasonic.slow_cm
            )
            if us_clear:
                # First moment US went clear — start the +0.1 s timer.
                if self._reroute_clear_count == 0:
                    self._reroute_clear_count = 1
                    self._reroute_us_clear_since = now
                if now - self._reroute_us_clear_since >= 0.5:
                    self._reroute_phase = "drive_around"
                    self._reroute_phase_start = now
                    self._reroute_clear_count = 0
                    return
            else:
                # Reset the clear-streak if US sees the obstacle again.
                self._reroute_clear_count = 0

            # Camera-bbox safety fallback — keep the old edge logic so a
            # close-range obstacle outside the US cone still terminates.
            obs_cx = self._front_obstacle_cx()
            if obs_cx is not None:
                if self._reroute_omega_sign < 0 and obs_cx > fw * 0.85:
                    self._reroute_phase = "drive_around"
                    self._reroute_phase_start = now
                    self._reroute_clear_count = 0
                    return
                if self._reroute_omega_sign > 0 and obs_cx < fw * 0.15:
                    self._reroute_phase = "drive_around"
                    self._reroute_phase_start = now
                    self._reroute_clear_count = 0
                    return

            if phase_elapsed > 2.5:
                # Hard timeout: don't spin forever if the sensor flickers.
                print("[Reroute] turn_away timeout — driving anyway.")
                self._reroute_phase = "drive_around"
                self._reroute_phase_start = now
                self._reroute_clear_count = 0
                return

            omega = self._reroute_omega_sign * 25
            self.uart.send(cmd_vector(0, 0, omega))
            self.line_follower.debug_vx = 0
            self.line_follower.debug_vy = 0
            self.line_follower.debug_omega = omega
            return

        # ===== Phase 2: drive forward past the obstacle =====
        # Per user spec (2026-04-23): rotate 90°, then **drive forward for
        # 2 seconds** (don't navigate around the obstacle, just sidestep
        # past it), then rotate 90° back and search for the marker.
        # Ultrasonic safety overrides the timer — if something appears
        # within slow_cm during the drive, abort to turn_away with a fresh
        # side choice rather than ramming it.
        DRIVE_AROUND_SECONDS = 2.5
        if self._reroute_phase == "drive_around":
            us_cm_now = self.uart.get_distance() if not self.no_ultrasonic else -1.0
            us_unsafe = (
                not self.no_ultrasonic
                and 0 < us_cm_now < self.config.ultrasonic.slow_cm
            )
            if us_unsafe:
                print(f"[Reroute] US={us_cm_now:.0f}cm during sidestep — re-rotating.")
                self._reroute_phase = "turn_away"
                self._reroute_phase_start = now
                self._reroute_omega_sign = self._choose_reroute_side()
                return

            if phase_elapsed >= DRIVE_AROUND_SECONDS:
                self._reroute_phase = "turn_back"
                self._reroute_phase_start = now
            else:
                self.uart.send(cmd_vector(25, 0, 0))
                self.line_follower.debug_vx = 25
                self.line_follower.debug_vy = 0
                self.line_follower.debug_omega = 0
                return

        # ===== Phase 3: turn back toward the tag =====
        if self._reroute_phase == "turn_back":
            # Spin opposite direction. Stop the moment the target marker shows.
            target_visible = False
            if self.aruco_detector:
                markers = self._last_markers
                if self._aruco_target_id is not None:
                    target_visible = any(m["id"] == self._aruco_target_id for m in markers)
                else:
                    target_visible = bool(markers)

            if target_visible:
                print("[Reroute] Tag reacquired — resuming approach.")
                if self.speaker:
                    self.speaker.say("Back on track.")
                self._reset_reroute()
                self.transition(State.ARUCO_APPROACH)
                return

            if phase_elapsed > 2.5:
                # Couldn't find it by pure rotation; let ARUCO_SEARCH take
                # over (it already biases the spin by _aruco_last_cx).
                print("[Reroute] turn_back complete without reacquisition — handing off to search.")
                self._reset_reroute()
                self.transition(State.ARUCO_SEARCH)
                return

            omega = -self._reroute_omega_sign * 25
            self.uart.send(cmd_vector(0, 0, omega))
            self.line_follower.debug_vx = 0
            self.line_follower.debug_vy = 0
            self.line_follower.debug_omega = omega
            return

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
        """Follow a person using face tracking.

        Behaves like line-follow: smooth proportional control on both the
        forward speed (by face size) and heading (by face lateral position).
        Face size is measured as fraction of frame width so the stop distance
        stays correct at any resolution. Same omega sign convention as the
        line follower: face on the right → positive omega → spin right (CW).

        On a single lost frame we rotate in place scanning, rather than
        bailing to PATROL — one blink shouldn't abort the follow.
        """
        if not self.person_detector or self._last_frame is None:
            self.transition(State.IDLE)
            return

        faces = self.person_detector.detect_faces(self._last_frame)
        self._last_faces = faces

        frame_h, frame_w = self._last_frame.shape[:2]

        if not faces:
            # Nothing in view this frame. Rotate-and-scan for a few seconds
            # before giving up, the way a butler would look around.
            if self._person_lost_since is None:
                self._person_lost_since = time.monotonic()
            lost_for = time.monotonic() - self._person_lost_since
            if lost_for > 4.0:
                if self.speaker:
                    self.speaker.say("I seem to have lost you.")
                self.uart.send(cmd_stop())
                self._person_smooth_cx = None
                self._person_smooth_bw = None
                self._person_lost_since = None
                self._person_greeted = False
                self.transition(State.IDLE)
                return
            # Slow scan — same sweep speed as ArUco search.
            self.uart.send(cmd_vector(0, 0, 8))
            self.line_follower.debug_vx = 0
            self.line_follower.debug_vy = 0
            self.line_follower.debug_omega = 8
            return

        # Re-acquired: reset lost timer.
        self._person_lost_since = None

        # Biggest face = closest person.
        face = max(faces, key=lambda f: f["bbox"][2] * f["bbox"][3])
        cx_raw, _ = face["center"]
        bw_raw = face["bbox"][2]

        # EMA smoothing — without it, face-detection jitter makes the robot
        # oscillate heading.
        alpha = 0.4
        if self._person_smooth_cx is None:
            self._person_smooth_cx = cx_raw
            self._person_smooth_bw = bw_raw
        else:
            self._person_smooth_cx += alpha * (cx_raw - self._person_smooth_cx)
            self._person_smooth_bw += alpha * (bw_raw - self._person_smooth_bw)
        cx = self._person_smooth_cx
        bw = self._person_smooth_bw

        # Resolution-independent sizing: the face width as a fraction of the
        # frame width. ~0.25 means face fills a quarter of the frame → ~50 cm.
        size_frac = bw / max(1, frame_w)
        STOP_FRAC = 0.25     # stop at ~half a metre
        CENTER_TOL = 0.08    # 8 % of frame width = centered

        lateral_error = (cx - frame_w / 2) / (frame_w / 2)  # -1..+1

        # omega: face on right → error>0 → omega>0 (spin right, CW). Same
        # convention as line-follower turn_strengths.
        omega = int(lateral_error * 40)
        omega = max(-40, min(40, omega))

        # If way off-center, rotate in place before moving forward so we
        # don't drive past the person.
        if abs(lateral_error) > 0.35:
            vx = 0
        elif size_frac >= STOP_FRAC:
            vx = 0
            if not self._person_greeted:
                self.uart.send(cmd_buzzer(800, 200))
                if self.speaker:
                    self.speaker.say("Hello! How may I help you?")
                self._person_greeted = True
        else:
            # Scale speed by how close we are — full speed far away,
            # creep the last stretch.
            dist_ratio = size_frac / STOP_FRAC   # 0 far, 1 arrived
            vx = int(40 * (1.0 - dist_ratio * 0.7))
            vx = max(15, min(40, vx))

        # Kill tiny omega jitter inside the centered band.
        if abs(lateral_error) < CENTER_TOL:
            omega = 0

        self.uart.send(cmd_vector(vx, 0, omega))
        self.line_follower.debug_vx = vx
        self.line_follower.debug_vy = 0
        self.line_follower.debug_omega = omega

    def _tick_dancing(self):
        """Execute a dance routine with timed moves and music."""
        if self._dance_start is None:
            self._dance_start = time.monotonic()
            # Play music through speaker
            self._play_dance_music()

        elapsed = time.monotonic() - self._dance_start

        if elapsed >= self._dance_duration:
            self.uart.send(cmd_stop())
            self._dance_start = None
            self._stop_dance_music()
            self.transition(State.IDLE)
            return

        # More dynamic dance with 8 phases
        phase = int(elapsed / 0.4) % 8
        moves = [
            (0, 0, 50),     # spin right
            (25, 25, 0),    # diagonal forward-right
            (0, 0, -50),    # spin left
            (25, -25, 0),   # diagonal forward-left
            (-20, 0, 0),    # backward
            (0, 30, 0),     # strafe right
            (0, -30, 0),    # strafe left
            (0, 0, 70),     # fast spin
        ]
        vx, vy, omega = moves[phase]
        self.uart.send(cmd_vector(vx, vy, omega))
        self.line_follower.debug_vx = vx
        self.line_follower.debug_vy = vy
        self.line_follower.debug_omega = omega

        # Rainbow LEDs already set via transition()
        if self.leds and elapsed < 0.1:
            self.leds.rainbow_cycle(speed=0.03, duration=self._dance_duration)

    def _play_dance_music(self):
        """Play dance music through speaker using audio file."""
        import subprocess
        import threading
        def _play():
            try:
                import os
                music_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                        "assets", "sounds")
                music_file = None
                for name in ["butterfly.mp3", "dance.mp3", "dance.wav"]:
                    path = os.path.join(music_dir, name)
                    if os.path.exists(path):
                        music_file = path
                        break
                if not music_file:
                    print("[Dance] No music file found in assets/sounds/")
                    return

                # Try multiple players in order of preference
                players = [
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", music_file],
                    ["mpg123", "-q", music_file],
                    ["cvlc", "--play-and-exit", "--no-video", "-q", music_file],
                    ["aplay", music_file],
                ]
                for cmd in players:
                    try:
                        self._dance_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        self._dance_proc.wait(timeout=15)
                        return
                    except FileNotFoundError:
                        continue
                    except subprocess.TimeoutExpired:
                        self._dance_proc.kill()
                        return
                print("[Dance] No audio player found. Install: sudo apt install ffmpeg")
            except Exception as e:
                print(f"[Dance] Music error: {e}")
        self._dance_music_thread = threading.Thread(target=_play, daemon=True)
        self._dance_music_thread.start()

    def _stop_dance_music(self):
        """Stop dance music."""
        try:
            if hasattr(self, '_dance_proc') and self._dance_proc and self._dance_proc.poll() is None:
                self._dance_proc.kill()
                self._dance_proc = None
        except Exception:
            pass

    def _tick_photo(self):
        """Capture a photo from camera into photos/ gallery folder."""
        if self._photo_taken:
            self.transition(State.IDLE)
            return

        if self.camera and self.camera.is_available:
            frame = self.camera.read_frame()
            if frame is not None:
                try:
                    import cv2
                    import os
                    photo_dir = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        "photos",
                    )
                    os.makedirs(photo_dir, exist_ok=True)
                    stamp = time.strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(photo_dir, f"photo_{stamp}.jpg")
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
