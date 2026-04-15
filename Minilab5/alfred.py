"""Sonny V4 — Alfred Robotic Butler entry point.

Usage:
    python Minilab5/alfred.py                  # run with GUI
    python Minilab5/alfred.py --headless       # run without GUI
    python Minilab5/alfred.py --no-voice       # skip voice subsystem
    python Minilab5/alfred.py --no-camera      # skip camera subsystem
    python Minilab5/alfred.py --test-vision    # run vision test and exit
    python Minilab5/alfred.py --test-voice     # run voice test and exit
    python Minilab5/alfred.py --speed 50       # override default speed
"""

import argparse
import sys
import os
import time

# Ensure project root is on sys.path so alfred package is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alfred.config import CONFIG
from alfred.fsm.controller import AlfredFSM


def run_vision_test():
    """Quick vision subsystem test."""
    from alfred.vision.camera import CameraManager
    from alfred.vision.aruco import ArucoDetector
    from alfred.vision.person import PersonDetector

    print("=== Vision Test ===")

    cam = CameraManager()
    if not cam.open():
        print("Camera not available. Test aborted.")
        return

    aruco = ArucoDetector()
    person = PersonDetector()

    print("Press Ctrl+C to stop...")
    try:
        import cv2
        while True:
            frame = cam.read_frame()
            if frame is None:
                continue

            markers = aruco.detect(frame)
            faces = person.detect_faces(frame)
            hands = person.detect_hands(frame)

            # Draw markers
            for m in markers:
                pts = m["corners"].astype(int)
                cv2.polylines(frame, [pts], True, (0, 255, 0), 2)
                cv2.putText(frame, f"ID:{m['id']}", tuple(pts[0]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            # Draw faces
            for f in faces:
                x, y, w, h = f["bbox"]
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)

            # Draw hand landmarks
            for hand in hands:
                for lx, ly, _ in hand["landmarks"]:
                    cv2.circle(frame, (lx, ly), 3, (0, 0, 255), -1)

            cv2.putText(frame, f"ArUco: {len(markers)}  Faces: {len(faces)}  Hands: {len(hands)}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("Sonny Vision Test", frame)

            if cv2.waitKey(1) & 0xFF == 27:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cam.close()
        person.close()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
    print("Vision test complete.")


def run_voice_test():
    """Quick voice subsystem test."""
    from alfred.voice.listener import VoiceListener
    from alfred.voice.intent import IntentClassifier
    from alfred.voice.speaker import Speaker

    print("=== Voice Test ===")

    speaker = Speaker()
    classifier = IntentClassifier()

    speaker.say("greet")
    time.sleep(2)

    def on_speech(text):
        intent, conf = classifier.classify(text)
        print(f"  Heard: '{text}' -> {intent} ({conf:.1f})")
        speaker.say(intent if intent != "unknown" else "confused")

    listener = VoiceListener()
    listener.on_speech(on_speech)
    listener.start()

    print(f"Listening for wake phrase: '{CONFIG.voice.wake_phrase}'")
    print("Press Ctrl+C to stop...")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
    print("Voice test complete.")


def _run_headless_dashboard(fsm):
    """Run FSM with a rich terminal dashboard showing all subsystem status.

    Prints a refreshing status block every 0.5s so you can monitor the robot
    over SSH without a display.
    """
    from alfred.fsm.states import STATE_NAMES, State

    fsm.start()
    tick_interval = 1.0 / 30.0
    display_interval = 0.5  # refresh terminal every 500ms
    last_display = 0
    last_voice_text = ""
    last_state = None
    event_log = []  # recent events

    try:
        while fsm._running:
            t0 = time.monotonic()
            fsm.tick()

            # Track events
            if fsm.state != last_state:
                old_name = STATE_NAMES.get(last_state, "---") if last_state is not None else "---"
                new_name = STATE_NAMES.get(fsm.state, "???")
                event_log.append(f"  {time.strftime('%H:%M:%S')}  {old_name} -> {new_name}")
                if len(event_log) > 8:
                    event_log.pop(0)
                last_state = fsm.state

            if fsm.voice_listener and fsm.voice_listener.last_text != last_voice_text:
                last_voice_text = fsm.voice_listener.last_text
                if last_voice_text:
                    event_log.append(f"  {time.strftime('%H:%M:%S')}  Voice: \"{last_voice_text}\"")
                    if len(event_log) > 8:
                        event_log.pop(0)

            # Terminal display at lower rate
            now = time.monotonic()
            if now - last_display >= display_interval:
                last_display = now
                _print_dashboard(fsm, event_log)

            elapsed = time.monotonic() - t0
            sleep_time = tick_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        fsm.stop()


def _print_dashboard(fsm, event_log):
    """Print a terminal dashboard block."""
    from alfred.fsm.states import STATE_NAMES

    state_name = STATE_NAMES.get(fsm.state, "???")
    lf = fsm.line_follower
    uart = fsm.uart

    # Read sensor data
    ir_bits = [0, 0, 0, 0, 0]
    dist_cm = -1.0
    if uart and uart.is_open:
        ir_bits = uart.get_ir_bits()
        dist_cm = uart.get_distance()

    vx = lf.debug_vx if lf else 0
    vy = lf.debug_vy if lf else 0
    omega = lf.debug_omega if lf else 0
    speed = lf.current_speed if lf else 0
    algo_speed = lf.internal_speed if lf else 0.0

    # IR sensor visual
    sensor_labels = ['W', 'NW', ' N', 'NE', ' E']
    ir_display = "  ".join(
        f"\033[92m[{sensor_labels[i]}]\033[0m" if ir_bits[i] else f"\033[90m {sensor_labels[i]} \033[0m"
        for i in range(5)
    )

    # Ultrasonic
    if dist_cm > 0 and dist_cm < 20:
        dist_str = f"\033[91m{dist_cm:.0f}cm BLOCKED\033[0m"
    elif dist_cm > 0:
        dist_str = f"\033[92m{dist_cm:.0f}cm\033[0m"
    else:
        dist_str = "\033[90m---\033[0m"

    # Voice
    voice_text = ""
    lang = "EN"
    if fsm.voice_listener:
        voice_text = fsm.voice_listener.last_text or ""
        lang = fsm.voice_listener.language.upper()

    # Face count
    face_count = len(fsm._last_faces) if fsm._last_faces else 0

    # Clear and print
    print("\033[2J\033[H", end="")  # clear screen, cursor to top
    print("=" * 60)
    print(f"  \033[96mSONNY V4\033[0m — Project Alfred    {time.strftime('%H:%M:%S')}")
    print("=" * 60)
    print()
    print(f"  State:    \033[93m{state_name:12s}\033[0m     Speed: {speed}")
    print(f"  Language: {lang}                  Algo:  {algo_speed:.1f}")
    print()
    print(f"  ┌─ IR Sensors ──────────────────────────────┐")
    print(f"  │  {ir_display}  │")
    print(f"  └─────────────────────────────────────────────┘")
    print()
    print(f"  Ultrasonic:  {dist_str}")
    print(f"  Movement:    vx:{vx:+4d}   vy:{vy:+4d}   omega:{omega:+4d}")
    print(f"  Faces:       {face_count}    Voice: \"{voice_text}\"")
    print()
    print(f"  ┌─ Event Log ──────────────────────────────────┐")
    for e in event_log[-6:]:
        print(f"  │{e:50s}│")
    remaining = 6 - len(event_log[-6:])
    for _ in range(remaining):
        print(f"  │{' ':50s}│")
    print(f"  └──────────────────────────────────────────────┘")
    print()
    print(f"  \033[90mCtrl+C to quit\033[0m")


def main():
    parser = argparse.ArgumentParser(description="Sonny V4 — Alfred Robotic Butler")
    parser.add_argument("--headless", action="store_true", help="Run without GUI")
    parser.add_argument("--no-voice", action="store_true", help="Skip voice subsystem")
    parser.add_argument("--no-camera", action="store_true", help="Skip camera subsystem")
    parser.add_argument("--test-vision", action="store_true", help="Run vision test and exit")
    parser.add_argument("--test-voice", action="store_true", help="Run voice test and exit")
    parser.add_argument("--speed", type=int, default=CONFIG.speed.default_speed,
                        help=f"Override default speed (default: {CONFIG.speed.default_speed})")
    args = parser.parse_args()

    print("Sonny V4 — Alfred Robotic Butler")

    if args.test_vision:
        run_vision_test()
        return
    if args.test_voice:
        run_voice_test()
        return

    # Build FSM
    fsm = AlfredFSM(
        config=CONFIG,
        headless=args.headless,
        no_voice=args.no_voice,
        no_camera=args.no_camera,
    )

    if args.speed != CONFIG.speed.default_speed:
        fsm.line_follower.current_speed = args.speed

    # GUI mode
    gui = None
    if not args.headless:
        try:
            from alfred.gui.debug_gui import DebugGUI
            gui = DebugGUI(fsm=fsm)
            gui.start()
            fsm.set_gui(gui)
            print("GUI started. Press M for auto/manual, F for follow, ESC to quit.")
        except Exception as e:
            print(f"GUI unavailable ({e}), running headless")
            gui = None

    if gui:
        # GUI event loop drives the tick rate
        fsm.start()
        try:
            while gui.is_running() and fsm._running:
                t0 = time.monotonic()
                fsm.tick()
                if not gui.update():
                    break
                # Rate limit FSM to ~30Hz, GUI runs at 60Hz internally
                elapsed = time.monotonic() - t0
                sleep_time = (1.0 / 30.0) - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
        finally:
            gui.stop()
            fsm.stop()
    else:
        # Headless mode with rich terminal dashboard
        _run_headless_dashboard(fsm)


if __name__ == "__main__":
    main()
