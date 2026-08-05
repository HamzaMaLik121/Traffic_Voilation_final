"""
Manual Lane Detector
Uses lane boundaries defined interactively via setup_lanes.py
"""

import cv2
import json
import numpy as np
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "lane_config.json"

LANE_COLORS = [
    (0,  220, 255),
    (80, 255, 80),
    (255, 80, 200),
    (255, 180, 0),
    (80,  80, 255),
    (255, 255, 80),
    (255, 100, 100),
]
FILL_ALPHA = 0.12


def _catmull_rom_segment(p0, p1, p2, p3, n=12):
    results = []
    for i in range(n):
        t  = i / n
        t2 = t * t
        t3 = t2 * t
        x = 0.5 * ((2*p1[0]) + (-p0[0]+p2[0])*t
                   + (2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2
                   + (-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3)
        y = 0.5 * ((2*p1[1]) + (-p0[1]+p2[1])*t
                   + (2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2
                   + (-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3)
        results.append((int(x), int(y)))
    return results


def smooth_polyline(pts, n_per_seg=12):
    if len(pts) < 2:
        return list(pts)
    if len(pts) == 2:
        x0, y0 = pts[0]; x1, y1 = pts[1]
        return [(int(x0 + (x1-x0)*i/n_per_seg),
                 int(y0 + (y1-y0)*i/n_per_seg)) for i in range(n_per_seg+1)]

    padded = [pts[0]] + list(pts) + [pts[-1]]
    smooth = []
    for i in range(1, len(padded) - 2):
        smooth.extend(_catmull_rom_segment(
            padded[i-1], padded[i], padded[i+1], padded[i+2], n_per_seg))
    smooth.append(tuple(pts[-1]))
    return smooth


class ManualLaneDetector:
    VIOL_THRESHOLD = 3

    def __init__(self, config_path=None, viol_threshold=None):
        self.viol_threshold  = viol_threshold or self.VIOL_THRESHOLD
        self._config_path    = Path(config_path or CONFIG_PATH)
        self._raw_lanes      = []
        self._smooth_lanes   = []
        self._cross_cnt      = {}
        self._last_left  = []
        self._last_right = []

        self._load_config()

    def _load_config(self):
        if not self._config_path.exists():
            raise FileNotFoundError(
                f"Lane config not found: {self._config_path}\n"
                "Run  python setup_lanes.py  first to define lane boundaries."
            )
        with open(self._config_path) as f:
            cfg = json.load(f)

        raw = cfg.get("lanes", [])
        if not raw:
            raise ValueError("Lane config has no lanes. Re-run setup_lanes.py.")

        self._raw_lanes = [
            [(int(p[0]), int(p[1])) for p in lane]
            for lane in raw
        ]
        self._smooth_lanes = [smooth_polyline(lane) for lane in self._raw_lanes]

        self._last_left  = self._smooth_lanes[0]  if self._smooth_lanes      else []
        self._last_right = self._smooth_lanes[-1] if len(self._smooth_lanes) > 1 else []

        print(f"  [OK] Manual lane config: {len(self._raw_lanes)} lanes loaded "
              f"from {self._config_path.name}")
        for i, lane in enumerate(self._raw_lanes):
            print(f"       Lane {i+1}: {len(lane)} control points  ->  "
                  f"{len(self._smooth_lanes[i])} smooth points")

    def detect_lanes(self, frame, vehicles=None):
        return self._last_left, self._last_right

    def detect_lane_violations(self, frame, vehicles):
        viols    = []
        segments = self._build_segments()
        h        = frame.shape[0]

        for vehicle in vehicles:
            x1, y1, x2, y2 = vehicle["bbox"]
            cx  = (x1 + x2) // 2
            cy  = y2
            vid = f"{(cx // 80) * 80}_{(cy // 80) * 80}"

            tol     = int(18 + max(0.0, min(1.0, cy / h)) * 18)
            on_line = self._point_near_segments(cx, cy, segments, tol)

            if on_line:
                self._cross_cnt[vid] = self._cross_cnt.get(vid, 0) + 1
            else:
                self._cross_cnt[vid] = max(0, self._cross_cnt.get(vid, 0) - 1)

            if self._cross_cnt.get(vid, 0) >= self.viol_threshold:
                viols.append({
                    "type":         "LANE_VIOLATION",
                    "vehicle_bbox": vehicle["bbox"],
                    "vehicle_type": vehicle.get("class_name", "vehicle"),
                    "confidence":   vehicle.get("confidence", 0.5),
                })
                self._cross_cnt[vid] = 0

        return viols

    def draw_lanes(self, frame, lanes=None):
        n = len(self._smooth_lanes)
        for idx, lane in enumerate(self._smooth_lanes):
            if len(lane) < 2:
                continue
            color = LANE_COLORS[idx % len(LANE_COLORS)]

            if idx < n - 1:
                next_lane = self._smooth_lanes[idx + 1]
                if len(next_lane) >= 2:
                    poly = np.array(
                        list(lane) + list(reversed(next_lane)), dtype=np.int32
                    )
                    over = frame.copy()
                    fill = LANE_COLORS[(idx + 2) % len(LANE_COLORS)]
                    cv2.fillPoly(over, [poly], fill)
                    cv2.addWeighted(over, FILL_ALPHA, frame, 1 - FILL_ALPHA, 0, frame)

            pts_arr = np.array(lane, dtype=np.int32)
            cv2.polylines(frame, [pts_arr], False, color, 3, cv2.LINE_AA)

            for pt in self._raw_lanes[idx]:
                cv2.circle(frame, pt, 4, color, -1)

        return frame

    def draw_violations(self, frame, violations):
        for v in violations:
            x1, y1, x2, y2 = v["vehicle_bbox"]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 100, 255), 3)
            cv2.putText(
                frame, "LANE VIOLATION", (x1, y1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2,
            )
        return frame

    def _build_segments(self):
        segs = []
        for lane in self._smooth_lanes:
            for i in range(len(lane) - 1):
                segs.append((*lane[i], *lane[i + 1]))
        return segs

    @staticmethod
    def _point_near_segments(px, py, segments, tol):
        for (x1, y1, x2, y2) in segments:
            dx, dy = x2 - x1, y2 - y1
            if dx == 0 and dy == 0:
                continue
            t      = max(0.0, min(1.0, ((px-x1)*dx + (py-y1)*dy) / (dx*dx + dy*dy)))
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            if ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5 < tol:
                return True
        return False
