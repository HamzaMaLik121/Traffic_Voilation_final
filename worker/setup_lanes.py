"""
Lane Setup Tool -- Interactive Freeform Lane Drawing
Run ONCE per camera to define lane boundaries:
    python setup_lanes.py [optional_video_or_image_path]

Controls:
  Left-click    : Add point to current lane
  Right-click   : Finish current lane, start next lane
  Z             : Undo last point
  R             : Delete entire last lane
  C             : Clear all lanes and start over
  S             : Save and exit
  Q / ESC       : Quit without saving
"""

import cv2
import json
import sys
import numpy as np
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

CONFIG_PATH = ROOT / "config" / "lane_config.json"

LANE_COLORS = [
    (0,  220, 255),
    (80, 255, 80),
    (255, 80, 200),
    (255, 180, 0),
    (80,  80, 255),
    (255, 255, 80),
    (255, 100, 100),
]

lanes       = []
current     = []
frame_orig  = None


def _catmull_rom_segment(p0, p1, p2, p3, n=12):
    results = []
    for i in range(n):
        t  = i / n
        t2 = t * t
        t3 = t2 * t
        x = 0.5 * ((2*p1[0])
                   + (-p0[0] + p2[0]) * t
                   + (2*p0[0] - 5*p1[0] + 4*p2[0] - p3[0]) * t2
                   + (-p0[0] + 3*p1[0] - 3*p2[0] + p3[0]) * t3)
        y = 0.5 * ((2*p1[1])
                   + (-p0[1] + p2[1]) * t
                   + (2*p0[1] - 5*p1[1] + 4*p2[1] - p3[1]) * t2
                   + (-p0[1] + 3*p1[1] - 3*p2[1] + p3[1]) * t3)
        results.append((int(x), int(y)))
    return results


def smooth_polyline(pts, n_per_seg=12):
    if len(pts) < 2:
        return pts
    if len(pts) == 2:
        x0, y0 = pts[0]; x1, y1 = pts[1]
        return [(int(x0 + (x1-x0)*i/n_per_seg),
                 int(y0 + (y1-y0)*i/n_per_seg)) for i in range(n_per_seg+1)]
    padded = [pts[0]] + list(pts) + [pts[-1]]
    smooth = []
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i-1], padded[i], padded[i+1], padded[i+2]
        smooth.extend(_catmull_rom_segment(p0, p1, p2, p3, n_per_seg))
    smooth.append(pts[-1])
    return smooth


def _draw_lane(img, raw_pts, color, label=None, drawing=False):
    if not raw_pts:
        return
    pts = [(int(p[0]), int(p[1])) for p in raw_pts]
    if len(pts) >= 2:
        smooth = smooth_polyline(pts)
        for i in range(len(smooth) - 1):
            thickness = 2 if drawing else 3
            cv2.line(img, smooth[i], smooth[i+1], color, thickness, cv2.LINE_AA)
    for pt in pts:
        cv2.circle(img, pt, 5, color, -1)
        cv2.circle(img, pt, 6, (255,255,255), 1)
    if label and pts:
        cv2.putText(img, label, (pts[0][0]+8, pts[0][1]-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def redraw(win_name):
    disp = frame_orig.copy()
    h, w = disp.shape[:2]
    overlay = disp.copy()
    cv2.rectangle(overlay, (0, 0), (w, 145), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, disp, 0.45, 0, disp)

    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(disp, "LANE SETUP  --  FREEFORM DRAWING", (12, 28),
                font, 0.8, (0, 255, 255), 2)
    cv2.putText(disp, "Left-click: add point  |  Right-click: FINISH lane  |  Z: undo point",
                (12, 55), font, 0.45, (220, 220, 220), 1)
    cv2.putText(disp, "R: delete last lane  |  C: clear all  |  S: SAVE & exit  |  Q/ESC: quit",
                (12, 78), font, 0.45, (220, 220, 220), 1)

    status_col = (0, 200, 255) if current else (180, 180, 180)
    cv2.putText(disp,
                f"Finished lanes: {len(lanes)}   Current lane points: {len(current)}",
                (12, 110), font, 0.48, status_col, 1)

    for idx, lane in enumerate(lanes):
        color = LANE_COLORS[idx % len(LANE_COLORS)]
        _draw_lane(disp, lane, color, label=f"Lane {idx+1}")

    if current:
        color_cur = LANE_COLORS[len(lanes) % len(LANE_COLORS)]
        _draw_lane(disp, current, color_cur, label=f"Lane {len(lanes)+1}", drawing=True)

    cv2.imshow(win_name, disp)


def mouse_cb(event, x, y, flags, param):
    global lanes, current
    if event == cv2.EVENT_LBUTTONDOWN:
        current.append([x, y])
        redraw(param)
    elif event == cv2.EVENT_RBUTTONDOWN:
        if len(current) >= 2:
            lanes.append(current.copy())
            current = []
            redraw(param)


def get_frame(source):
    p = Path(source) if source else None
    if p and p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp'):
        img = cv2.imread(str(p))
        if img is None:
            raise FileNotFoundError(f"Cannot read image: {p}")
        return img
    cap = cv2.VideoCapture(str(p) if p else 0)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open: {source}")
    if p:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(30, total // 4))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError("Could not read frame.")
    return frame


def main():
    global frame_orig, lanes, current

    source = sys.argv[1] if len(sys.argv) > 1 else None
    if source is None:
        source = 0

    print(f"\n  Lane Setup Tool")
    print(f"  Source : {source or 'webcam'}")
    print(f"  Config : {CONFIG_PATH}\n")

    frame_orig = get_frame(source or 0)
    frame_orig = cv2.resize(frame_orig, (1280, 720))

    win = "Lane Setup -- Draw Lanes"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 1280, 720)
    cv2.setMouseCallback(win, mouse_cb, win)

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            lanes = cfg.get("lanes", [])
            print(f"  Loaded {len(lanes)} existing lanes.  Press C to start fresh.\n")
        except Exception:
            pass

    redraw(win)

    while True:
        key = cv2.waitKey(30) & 0xFF
        if key in (ord('q'), 27):
            print("  Quit without saving.")
            break
        elif key == ord('z'):
            if current:
                current.pop()
                redraw(win)
            elif lanes:
                current = lanes.pop()
                redraw(win)
        elif key == ord('r'):
            if lanes:
                lanes.pop()
                redraw(win)
        elif key == ord('c'):
            lanes = []; current = []
            redraw(win)
        elif key == ord('s'):
            if len(current) >= 2:
                lanes.append(current.copy())
                current = []
            if not lanes:
                print("  [WARN] No lanes defined -- nothing saved.")
                continue
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            cfg = {
                "video_source": str(source or "webcam"),
                "frame_size":   [1280, 720],
                "lanes":        lanes,
                "lane_count":   len(lanes),
            }
            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
            print(f"\n  Saved {len(lanes)} lanes to {CONFIG_PATH}")
            break

        if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
