"""Alfred V4 FSM controller — main dispatch loop coordinating all subsystems."""

import time
import logging

from alfred.config import CONFIG
from alfred.fsm.states import State, STATE_NAMES
from alfred.comms.uart import UARTBridge
from alfred.comms.protocol import cmd_stop, cmd_vector
from alfred.navigation.line_follower import LineFollower, FollowState

logger = logging.getLogger(__name__)


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

        # Per-state context
        self._dance_start = None
        self._dance_duration = 5.0
        self._photo_taken = False
        self._aruco_target_id = None
        self._last_aruco_pose = None
        self._last_frame = None
        self._last_faces = []
        self._last_obstacles = []

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

        if self.personality:
            self.personality.express_greeting()

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
        """Transition to a new state."""
        if new_state == self.state:
            return
        old_name = STATE_NAMES[self.state]
        new_name = STATE_NAMES[new_state]
        print(f"[FSM] {old_name} -> {new_name}")
        self.state = new_state

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
        """Handle a recognised voice command."""
        if not self.intent_classifier:
            return

        intent, confidence = self.intent_classifier.classify(text)
        print(f"[Voice] '{text}' -> {intent} ({confidence:.1f})")

        intent_to_state = {
            "follow_track": State.FOLLOWING,
            "go_to_aruco":  State.ARUCO_SEARCH,
            "dance":        State.DANCING,
            "take_photo":   State.PHOTO,
            "come_here":    State.PERSON_APPROACH,
            "stop":         State.STOPPING,
            "sleep":        State.SLEEPING,
            "patrol":       State.PATROL,
        }

        if intent in intent_to_state:
            target = intent_to_state[intent]
            if target == State.FOLLOWING:
                self.line_follower.reset()
            elif target == State.DANCING:
                self._dance_start = time.monotonic()
            elif target == State.PHOTO:
                self._photo_taken = False
            self.transition(target)
        elif self.personality:
            self.personality.express_confusion()

    # -- State tick handlers ------------------------------------------------

    def _tick_idle(self):
        """Wait for voice command or GUI input. Check for wake word."""
        if self.voice_listener and self.voice_listener.is_wake_word_detected():
            self.transition(State.LISTENING)

    def _tick_listening(self):
        """Actively listening for a command after wake word.
        Times out back to IDLE after 5 seconds of no command."""
        # The voice listener callback handles commands automatically.
        # This state just shows the listening expression.
        pass

    def _tick_following(self):
        """Run line follower and mirror sub-FSM transitions."""
        ir_bits = self.uart.get_ir_bits()
        command = self.line_follower.tick(ir_bits)
        self.uart.send(command)

        # Check for obstacles while following
        if self.obstacle_detector and self._last_frame is not None:
            if not self.obstacle_detector.is_path_clear(self._last_frame):
                self.transition(State.BLOCKED)
                return

        # Mirror sub-FSM state transitions
        if self.line_follower.finished:
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
        if self.aruco_detector and self._last_frame is not None:
            markers = self.aruco_detector.detect(self._last_frame)
            if markers:
                # Found a marker — start approach
                self._aruco_target_id = markers[0]["id"]
                pose = self.aruco_detector.estimate_pose(markers[0])
                if pose:
                    self._last_aruco_pose = pose
                self.transition(State.ARUCO_APPROACH)
                return

        # Slow rotation to scan for markers
        self.uart.send(cmd_vector(0, 0, 30))
        self.line_follower.debug_vx = 0
        self.line_follower.debug_vy = 0
        self.line_follower.debug_omega = 30

    def _tick_aruco_approach(self):
        """Drive toward detected ArUco marker."""
        if not self.aruco_detector or not self.aruco_approach or self._last_frame is None:
            self.transition(State.IDLE)
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

        pose = self.aruco_detector.estimate_pose(target_marker)
        if pose and self.aruco_approach.is_arrived(pose["tvec"]):
            self.uart.send(cmd_stop())
            print(f">>> Arrived at ArUco marker {self._aruco_target_id}")
            self.transition(State.IDLE)
            return

        if pose:
            vx, vy, omega = self.aruco_approach.compute_approach(pose["tvec"], pose["rvec"])
        else:
            # No pose estimation (no camera calibration) — use visual centering
            vx, vy, omega = self.aruco_detector.compute_approach_vector(pose)

        self.uart.send(cmd_vector(int(vx), int(vy), int(omega)))
        self.line_follower.debug_vx = int(vx)
        self.line_follower.debug_vy = int(vy)
        self.line_follower.debug_omega = int(omega)

    def _tick_blocked(self):
        """Stop and wait, then try rerouting."""
        self.uart.send(cmd_stop())
        self.line_follower.debug_vx = 0
        self.line_follower.debug_vy = 0
        self.line_follower.debug_omega = 0

        # Check if path cleared
        if self.obstacle_detector and self._last_frame is not None:
            if self.obstacle_detector.is_path_clear(self._last_frame):
                # Path cleared — resume following
                self.line_follower.reset()
                self.transition(State.FOLLOWING)
                return

        # Try rerouting after being blocked
        self.transition(State.REROUTING)

    def _tick_rerouting(self):
        """Compute avoidance manoeuvre around obstacle."""
        if self.obstacle_avoider and self.obstacle_detector and self._last_frame is not None:
            obstacles = self.obstacle_detector.detect(self._last_frame)
            vx, vy, omega = self.obstacle_avoider.compute_avoidance(obstacles)

            if not self.obstacle_avoider.is_rerouting():
                # No more obstacles — resume following
                self.line_follower.reset()
                self.transition(State.FOLLOWING)
                return

            self.uart.send(cmd_vector(max(10, vx + 20), vy, omega))
            self.line_follower.debug_vx = vx + 20
            self.line_follower.debug_vy = vy
            self.line_follower.debug_omega = omega
        else:
            # No avoidance capability — just go back to following
            self.line_follower.reset()
            self.transition(State.FOLLOWING)

    def _tick_patrol(self):
        """Autonomous wander with person detection."""
        if not self.patrol_controller:
            self.transition(State.IDLE)
            return

        # Detect persons and obstacles
        faces = []
        obstacles = []
        if self.person_detector and self._last_frame is not None:
            faces = self.person_detector.detect_faces(self._last_frame)
            self._last_faces = faces
        if self.obstacle_detector and self._last_frame is not None:
            obstacles = self.obstacle_detector.detect(self._last_frame)
            self._last_obstacles = obstacles

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
            # Lost the person
            self.uart.send(cmd_stop())
            self.transition(State.PATROL)
            return

        # Approach the largest face
        face = max(faces, key=lambda f: f["bbox"][2] * f["bbox"][3])
        cx, cy = face["center"]
        bw, bh = face["bbox"][2], face["bbox"][3]
        frame_w = self.config.vision.resolution[0]

        # Proportional approach
        face_area = bw * bh
        target_area = 15000  # roughly "close enough"

        if face_area >= target_area:
            self.uart.send(cmd_stop())
            print(">>> Person reached")
            self.transition(State.IDLE)
            return

        # Drive forward + steer toward face center
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

        # Simple dance pattern: alternate moves every 0.5s
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

        # Trigger rainbow LEDs while dancing
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
        """Low-power sleep state. Wake on wake word."""
        # Keep checking for wake word
        if self.voice_listener and self.voice_listener.is_wake_word_detected():
            if self.personality:
                self.personality.express_greeting()
            self.transition(State.IDLE)

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
