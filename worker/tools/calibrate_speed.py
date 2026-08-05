"""
Speed Calibration Tool
Traffic Violation Detection System

Usage:
    python tools/calibrate_speed.py
    python tools/calibrate_speed.py path/to/video.mp4
"""

import cv2
import sys
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config.config import PIXEL_TO_METER_RATIO

click_points = []
frame_display = None


def mouse_callback(event, x, y, flags, param):
    global click_points, frame_display
    if event == cv2.EVENT_LBUTTONDOWN and len(click_points) < 2:
        click_points.append((x, y))
        cv2.circle(frame_display, (x, y), 7, (0, 255, 0), -1)
        cv2.putText(frame_display, f"P{len(click_points)} ({x},{y})",
                    (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        if len(click_points) == 2:
            cv2.line(frame_display, click_points[0], click_points[1], (0, 200, 255), 2)
            px_dist = ((click_points[1][0] - click_points[0][0])**2 +
                       (click_points[1][1] - click_points[0][1])**2) ** 0.5
            cv2.putText(frame_display,
                        f"Pixel distance: {px_dist:.1f} px",
                        (20, frame_display.shape[0] - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
        cv2.imshow("Speed Calibration Tool", frame_display)


def get_first_frame(source):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open: {source}")
        return None
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print("[ERROR] Cannot read first frame.")
        return None
    return frame


def compute_pixel_distance(p1, p2):
    return ((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2) ** 0.5


def save_ratio_to_config(new_ratio):
    config_path = ROOT / "config" / "config.py"
    text = config_path.read_text(encoding='utf-8')
    new_text = re.sub(
        r'(PIXEL_TO_METER_RATIO\s*=\s*)[0-9.]+',
        f'\\g<1>{new_ratio:.6f}',
        text
    )
    if new_text == text:
        print("[WARN] Could not find PIXEL_TO_METER_RATIO in config.py -- update manually.")
        return False
    config_path.write_text(new_text, encoding='utf-8')
    print(f"[OK] config/config.py updated: PIXEL_TO_METER_RATIO = {new_ratio:.6f}")
    return True


def run_calibration(source=None):
    global click_points, frame_display

    if source is None:
        source = 0

    print("\n" + "=" * 60)
    print("  SPEED CALIBRATION TOOL")
    print("=" * 60)
    print(f"\n  Video source : {source}")
    print(f"  Current ratio: {PIXEL_TO_METER_RATIO} m/px")
    print()
    print("  INSTRUCTIONS:")
    print("  1. A video frame will open.")
    print("  2. Click TWO points on the road that span a known distance.")
    print("  3. Press ENTER when done clicking.")
    print("  4. Enter the real-world distance in metres.")
    print()

    frame = get_first_frame(source)
    if frame is None:
        return

    frame = cv2.resize(frame, (1280, 720))
    frame_display = frame.copy()

    instructions = [
        "SPEED CALIBRATION",
        "Click 2 points spanning a known road distance",
        "Press ENTER when both points are placed",
        "Press R to reset, Q to quit without saving",
    ]
    for i, line in enumerate(instructions):
        cv2.putText(frame_display, line,
                    (20, 30 + i * 28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65 if i > 0 else 0.9,
                    (0, 255, 255) if i == 0 else (200, 200, 200),
                    2)

    cv2.namedWindow("Speed Calibration Tool", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("Speed Calibration Tool", mouse_callback)
    cv2.imshow("Speed Calibration Tool", frame_display)

    while True:
        key = cv2.waitKey(50) & 0xFF
        if key in (ord('r'), ord('R')):
            click_points = []
            frame_display = frame.copy()
            for i, line in enumerate(instructions):
                cv2.putText(frame_display, line,
                            (20, 30 + i * 28),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.65 if i > 0 else 0.9,
                            (0, 255, 255) if i == 0 else (200, 200, 200),
                            2)
            cv2.imshow("Speed Calibration Tool", frame_display)
            print("   [INFO] Reset -- click two new points.")
        elif key in (13, 10):
            if len(click_points) < 2:
                print("   [WARN] Please click 2 points first.")
                continue
            break
        elif key in (ord('q'), ord('Q')):
            print("\n   Calibration cancelled.")
            cv2.destroyAllWindows()
            return

    cv2.destroyAllWindows()

    p1, p2 = click_points[0], click_points[1]
    pixel_distance = compute_pixel_distance(p1, p2)

    print(f"\n  Point 1       : {p1}")
    print(f"  Point 2       : {p2}")
    print(f"  Pixel distance: {pixel_distance:.2f} px")

    while True:
        try:
            real_metres = float(input("\n  Enter the real-world distance in METRES: "))
            if real_metres <= 0:
                print("  [ERROR] Distance must be positive.")
                continue
            break
        except ValueError:
            print("  [ERROR] Please enter a number.")

    new_ratio = real_metres / pixel_distance

    print(f"\n  Calculated PIXEL_TO_METER_RATIO = {real_metres:.2f} / {pixel_distance:.2f} = {new_ratio:.6f} m/px")

    if new_ratio < 0.001:
        print("  [WARN] Warning: ratio is very small")
    elif new_ratio > 0.5:
        print("  [WARN] Warning: ratio is very large")
    else:
        print("  [OK] Ratio looks reasonable.")

    save_choice = input(f"\n  Save PIXEL_TO_METER_RATIO = {new_ratio:.6f} to config/config.py? [y/N]: ").strip().lower()
    if save_choice == 'y':
        if save_ratio_to_config(new_ratio):
            print("\n  [OK] Config updated.")
    else:
        print(f"\n  [INFO] To apply manually, edit config/config.py:")
        print(f"      PIXEL_TO_METER_RATIO = {new_ratio:.6f}")

    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    video_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_calibration(video_arg)
