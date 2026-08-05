"""
Master Live Test Script -- FULL INTEGRATED PIPELINE
Runs ALL detection modules simultaneously.

Usage:
    python live_test.py [optional_video_path]
"""

import cv2
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.append(str(ROOT))

from app.detection.vehicle_detector import VehicleDetector
from app.detection.helmet_detector import HelmetDetector
from app.detection.traffic_light_detector import TrafficLightDetector
from app.detection.lpr_detector import LPRDetector
from app.detection.speed_estimator import SpeedEstimator
from app.detection.lane_detector import LaneDetector
from app.detection.uturn_detector import UTurnDetector
from app.db.database import ViolationDatabase
from config.config import OUTPUT_DIR, SAVE_EVIDENCE, EVIDENCE_FORMAT


def _build_lane_detector():
    config_path = ROOT / "config" / "lane_config.json"
    if config_path.exists():
        try:
            from app.detection.manual_lane_detector import ManualLaneDetector
            ld = ManualLaneDetector(config_path)
            print("  [OK] Using Manual lane detector (from config/lane_config.json)")
            print("       Re-run  python setup_lanes.py  to update lane boundaries.")
            return ld
        except Exception as e:
            print(f"  [WARN] Manual lane config failed ({e})")

    try:
        from app.detection.yolop_lane_detector import YolopLaneDetector
        ld = YolopLaneDetector()
        print("  [INFO] Using YOLOP deep lane detector.")
        print("         Run  python setup_lanes.py  for angle-agnostic detection.")
        return ld
    except Exception as e:
        print(f"  [WARN] YOLOP failed ({e})")

    try:
        from app.detection.poly_lane_detector import PolyLaneDetector
        ld = PolyLaneDetector()
        print("  [INFO] Using Polynomial lane detector (fallback).")
        return ld
    except Exception as e:
        print(f"  [WARN] PolyLane failed ({e}) -- using Hough fallback.")

    return LaneDetector()


def save_evidence(frame, violation_type, frame_number, evidence_dir):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{violation_type}_{ts}_f{frame_number}.{EVIDENCE_FORMAT}"
    path = evidence_dir / filename
    cv2.imwrite(str(path), frame)
    return str(path)


def record_violation(db, violation, frame_number, video_path, evidence_path=None):
    db.add_violation({
        'violation_type': violation['type'],
        'timestamp': datetime.now(),
        'location': str(video_path) if video_path else 'webcam',
        'vehicle_type': violation.get('vehicle_type'),
        'license_plate': violation.get('license_plate'),
        'confidence': violation.get('confidence', 0.0),
        'speed': violation.get('speed'),
        'speed_limit': violation.get('speed_limit'),
        'evidence_image_path': evidence_path,
        'video_frame_number': frame_number,
        'metadata': {
            'bbox': violation.get('vehicle_bbox'),
        }
    })


def draw_hud(frame, fps, vehicles, violations_this_frame, total_saved):
    overlay = frame.copy()
    cv2.rectangle(overlay, (15, 15), (370, 185), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
    cv2.rectangle(frame, (15, 15), (370, 185), (0, 255, 255), 2)

    def put(text, y, color=(255, 255, 255)):
        cv2.putText(frame, text, (25, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, color, 2)

    put("TRAFFIC VIOLATION SYSTEM", 45, (0, 255, 255))
    put(f"FPS : {fps:5.1f}", 75)
    put(f"Vehicles     : {len(vehicles)}", 105, (0, 255, 0))
    put(f"Violations   : {violations_this_frame}", 135, (0, 80, 255))
    put(f"DB Records   : {total_saved}", 165, (255, 200, 0))
    return frame


def _find_video_source(user_source=None):
    """Find a working video source: user-specified path, data dir, or webcam"""
    # If user specified a path, try it
    if user_source and user_source != 0:
        src_path = Path(user_source)
        if src_path.exists():
            cap = cv2.VideoCapture(str(src_path))
            if cap.isOpened():
                cap.release()
                return str(src_path)
            cap.release()

    # Search recursively in /app/data for video files
    data_dir = Path("/app/data")
    if data_dir.exists():
        video_exts = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv')
        for f in sorted(data_dir.rglob('*')):
            if f.suffix.lower() in video_exts:
                cap = cv2.VideoCapture(str(f))
                if cap.isOpened():
                    cap.release()
                    print(f"  Found video: {f}")
                    return str(f)
                cap.release()

    # Fallback to webcam
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        cap.release()
        print("  Video : Webcam")
        return 0
    cap.release()

    # No video source found
    return None


def run_live_test(video_source=None):
    print("\n" + "=" * 65)
    print("  TRAFFIC VIOLATION DETECTION -- FULL INTEGRATED PIPELINE")
    print("=" * 65)

    print("\n  Loading AI engines ...")
    vd   = VehicleDetector()
    hd   = HelmetDetector()
    tld  = TrafficLightDetector()
    lprd = LPRDetector()
    se   = SpeedEstimator()
    ld   = _build_lane_detector()
    utd  = UTurnDetector()
    print("[OK] All detection modules ready.\n")

    db = ViolationDatabase()

    evidence_dir = OUTPUT_DIR / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Find a working video source
    resolved_source = _find_video_source(video_source)
    if resolved_source is None:
        print("\n" + "=" * 65)
        print("  NO VIDEO SOURCE AVAILABLE")
        print("=" * 65)
        print("  Could not find a video source (webcam, mounted files).")
        print("  The system initialized correctly but needs video data.")
        print("  Mount a video file at /app/data/ or pass a video path.")
        print("  For testing, run: docker compose exec worker python live_test.py /path/to/video.mp4")
        print()
        print("  Worker is staying alive, waiting for video...")
        print("=" * 65 + "\n")
        db.close()
        # Keep the container alive by polling
        while True:
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] Worker idle — no video source. Mount video at /app/data/")
            time.sleep(60)

    # Video source resolution
    if resolved_source == 0:
        video_source = 0
        print(" Video : Webcam")
    else:
        video_source = resolved_source
        print(f" Video : {video_source}")

    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open source: {video_source}")
        db.close()
        return

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(
        str(OUTPUT_DIR / "master_test_result.mp4"),
        fourcc, 20.0, (1280, 720)
    )

    HEADLESS = os.getenv('HEADLESS', '0') == '1'
    LOOP_VIDEO = os.getenv('LOOP_VIDEO', '0') == '1'

    if not HEADLESS:
        cv2.namedWindow("Traffic Violation System", cv2.WINDOW_NORMAL)

    frame_count    = 0
    total_saved    = 0
    vehicles       = []
    traffic_lights = []
    helmet_viols   = []
    speed_viols    = []
    lane_viols     = []
    uturn_viols    = []
    plates         = []
    all_violations = []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f" Processing ... (press Q to stop)\n")
    if LOOP_VIDEO:
        print(f" LOOP: ON — video will restart when it ends (max {total_frames} frames)")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            if LOOP_VIDEO and total_frames > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                print(f"\n 🔄 Video ended at frame {frame_count}. Restarting...")
                frame_count = 0
                continue
            break

        frame_count += 1
        frame = cv2.resize(frame, (1280, 720))
        t0 = time.time()

        if frame_count % 3 == 0:
            vehicles = vd.detect(frame)
            traffic_lights = tld.detect_traffic_lights(frame)
            helmet_viols = hd.detect_no_helmet_violation(frame, vehicles)
            speed_viols = se.estimate_speed(vehicles, frame_count)
            ld.detect_lanes(frame, vehicles)
            lane_viols = ld.detect_lane_violations(frame, vehicles)
            uturn_viols = utd.detect_uturn_violations(vehicles, frame_count)
            plates = lprd.detect_and_read(frame) if vehicles else []
            rl_viols = tld.detect_red_light_violation(frame, traffic_lights, vehicles)

            def _closest_plate(bbox):
                if not plates:
                    return None
                vx = (bbox[0] + bbox[2]) // 2
                vy = (bbox[1] + bbox[3]) // 2
                best, best_d = None, float('inf')
                for p in plates:
                    px = (p['bbox'][0] + p['bbox'][2]) // 2
                    py = (p['bbox'][1] + p['bbox'][3]) // 2
                    d  = ((vx - px) ** 2 + (vy - py) ** 2) ** 0.5
                    if d < best_d:
                        best_d, best = d, p['text']
                return best if best_d < 200 else None

            all_violations = helmet_viols + speed_viols + lane_viols + uturn_viols + rl_viols

        # ── Snapshot clean frame BEFORE drawing (for evidence without boxes) ─
        if SAVE_EVIDENCE and frame_count % 3 == 0:
            clean_frame = frame.copy()

        # ── Draw detection boxes on the frame (for live feed + output video) ─
        frame = vd.draw_detections(frame, vehicles)
        frame = tld.draw_traffic_lights(frame, traffic_lights)
        frame = hd.draw_violations(frame, helmet_viols)
        frame = lprd.draw_lpr(frame, plates)
        frame = ld.draw_lanes(frame)
        frame = ld.draw_violations(frame, lane_viols)
        frame = utd.draw_violations(frame, uturn_viols)
        frame = se.draw_speed_violations(frame, speed_viols)
        frame = se.draw_speed_info(frame, vehicles)

        fps = 1.0 / (time.time() - t0) if (time.time() - t0) > 0 else 0
        frame = draw_hud(frame, fps, vehicles, len(all_violations), total_saved)

        # ── Save evidence from CLEAN frame (no boxes, just the violation crop) ─
        if SAVE_EVIDENCE and frame_count % 3 == 0:
            for v in all_violations:
                bbox = v.get('vehicle_bbox') or v.get('bbox')
                if bbox:
                    x1, y1, x2, y2 = bbox
                    h_f, w_f = clean_frame.shape[:2]
                    pad  = 30
                    crop = clean_frame[
                        max(0, y1 - pad):min(h_f, y2 + pad),
                        max(0, x1 - pad):min(w_f, x2 + pad)
                    ]
                else:
                    crop = clean_frame

                ev_path = save_evidence(crop, v['type'], frame_count, evidence_dir)
                vbbox = v.get('vehicle_bbox', v.get('bbox', [0,0,0,0]))
                v['license_plate'] = _closest_plate(vbbox)
                record_violation(db, v, frame_count, video_source, ev_path)
                total_saved += 1

        print(
            f"\rFrame {frame_count:05d} | FPS {fps:5.1f} | "
            f"Vehicles {len(vehicles):2d} | "
            f"Violations {len(all_violations):2d} | "
            f"DB records {total_saved:4d}",
            end=""
        )

        cv2.imshow("Traffic Violation System", frame) if not HEADLESS else None
        out.write(frame)

        # Save latest annotated frame every 3 frames for live feed (atomic write)
        if frame_count % 3 == 0:
            latest_path = OUTPUT_DIR / "latest_frame.jpg"
            tmp_path = OUTPUT_DIR / "latest_frame_tmp.jpg"
            cv2.imwrite(str(tmp_path), frame)
            os.replace(str(tmp_path), str(latest_path))  # atomic on Linux

        if not HEADLESS and cv2.waitKey(1) & 0xFF == ord('q'):
            print("\n\n  Stopped by user.")
            break

    cap.release()
    out.release()
    cv2.destroyAllWindows()
    db.close()

    print("\n\n" + "=" * 65)
    print("  PROCESSING COMPLETE")
    print("=" * 65)
    print(f"  Total frames    : {frame_count}")
    print(f"  Violations saved: {total_saved}")
    print(f"  Evidence images : {evidence_dir}")
    print(f"  Output video    : {OUTPUT_DIR / 'master_test_result.mp4'}")
    print(f"  Database        : see outputs in database/ folder")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        run_live_test(src)
    except KeyboardInterrupt:
        print("\n  Interrupted.")
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        traceback.print_exc()
