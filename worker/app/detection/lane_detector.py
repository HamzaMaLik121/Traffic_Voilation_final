"""
Lane Violation Detection Module -- v3 (forward-camera aware)
"""

import cv2
import math
import numpy as np
from collections import defaultdict, deque
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))


class LaneDetector:
    ROI_TOP_RATIO    = 0.45
    ROI_TRAP_INSET   = 0.15
    VIOL_THRESHOLD   = 10
    HISTORY_LEN      = 5
    VOTE_MIN         = 2
    TOLERANCE_BASE   = 14
    TOLERANCE_NEAR   = 28

    def __init__(self, violation_frames_threshold=None):
        self.violation_threshold = violation_frames_threshold or self.VIOL_THRESHOLD
        self.crossing_counts  = defaultdict(int)
        self.lane_history     = defaultdict(lambda: deque(maxlen=10))
        self.last_lanes       = []
        self._frame_history   = deque(maxlen=self.HISTORY_LEN)
        self._vp              = None
        self._warmup          = 0

    def detect_lanes(self, frame, vehicles=None):
        h, w = frame.shape[:2]
        roi_top = int(h * self.ROI_TOP_RATIO)

        trap_mask = self._trap_mask(h, w, roi_top)

        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges   = cv2.Canny(blurred, 50, 150)

        if vehicles:
            edges = self._mask_vehicles(edges, vehicles, roi_top, h, w)

        edges = cv2.bitwise_and(edges, trap_mask)

        raw = cv2.HoughLinesP(
            edges,
            rho=1, theta=np.pi / 180,
            threshold=40,
            minLineLength=60,
            maxLineGap=50,
        )

        this_frame = []
        if raw is not None:
            for seg in raw:
                x1, y1, x2, y2 = seg[0]
                y1 += roi_top
                y2 += roi_top
                line = self._validate_line(x1, y1, x2, y2, h, w)
                if line:
                    this_frame.append(line)

        self._frame_history.append(this_frame)
        self._warmup += 1

        self._update_vp(this_frame, w, h)

        voted = self._vote(this_frame)
        self.last_lanes = voted if voted else (this_frame if self._warmup < 10 else [])
        return self.last_lanes

    def detect_lane_violations(self, frame, vehicles):
        lanes      = self.detect_lanes(frame, vehicles)
        violations = []
        h          = frame.shape[0]

        for vehicle in vehicles:
            x1, y1, x2, y2 = vehicle['bbox']
            cx = (x1 + x2) // 2
            cy = y2

            tol     = self._tolerance(cy, h)
            on_line = any(
                self._point_to_segment_dist(cx, cy, lx1, ly1, lx2, ly2) < tol
                for (lx1, ly1, lx2, ly2) in lanes
            )

            vid = f"{(cx // 100) * 100}_{(cy // 80) * 80}"

            if on_line:
                self.crossing_counts[vid] += 1
            else:
                self.crossing_counts[vid] = max(0, self.crossing_counts[vid] - 1)

            if self.crossing_counts[vid] >= self.violation_threshold:
                violations.append({
                    'type':          'LANE_VIOLATION',
                    'vehicle_bbox':  vehicle['bbox'],
                    'vehicle_type':  vehicle.get('class_name', 'vehicle'),
                    'confidence':    vehicle.get('confidence', 0.5),
                    'crossing_frames': self.crossing_counts[vid],
                })
                self.crossing_counts[vid] = 0

        return violations

    def draw_lanes(self, frame, lanes=None):
        draw_list = lanes if lanes is not None else self.last_lanes
        if not draw_list:
            return frame
        overlay = frame.copy()
        for (x1, y1, x2, y2) in draw_list:
            cv2.line(overlay, (x1, y1), (x2, y2), (0, 255, 255), 2)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
        return frame

    def draw_violations(self, frame, violations):
        for v in violations:
            x1, y1, x2, y2 = v['vehicle_bbox']
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 3)
            label = "LANE VIOLATION"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw, y1), (0, 165, 255), -1)
            cv2.putText(frame, label, (x1, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        return frame

    def _trap_mask(self, h, w, roi_top):
        mask = np.zeros((h, w), dtype=np.uint8)
        inset = int(w * self.ROI_TRAP_INSET)
        pts = np.array([
            [inset,         roi_top],
            [w - inset,     roi_top],
            [w,             h],
            [0,             h],
        ], dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)
        return mask

    def _mask_vehicles(self, edges, vehicles, roi_top, h, w):
        for v in vehicles:
            vx1, vy1, vx2, vy2 = v['bbox']
            vx1 = max(0, vx1 - 5)
            vx2 = min(w - 1, vx2 + 5)
            vy1 = max(0, vy1 - 5)
            vy2 = min(h - 1, vy2 + 10)
            edges[vy1:vy2, vx1:vx2] = 0
        return edges

    def _validate_line(self, x1, y1, x2, y2, h, w):
        if math.hypot(x2 - x1, y2 - y1) < 40:
            return None
        if abs(y2 - y1) < 5:
            return None
        if y1 < y2:
            x1, y1, x2, y2 = x2, y2, x1, y1
        if self._vp is not None:
            vp_x, vp_y = self._vp
            if abs(y1 - y2) > 1:
                t = (vp_y - y1) / (y2 - y1)
                proj_x = x1 + t * (x2 - x1)
                if abs(proj_x - vp_x) > w * 0.65:
                    return None
        return (x1, y1, x2, y2)

    def _update_vp(self, lines, w, h):
        if len(lines) < 2:
            if self._vp is None:
                self._vp = (w // 2, int(h * 0.40))
            return
        intersections = []
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                pt = self._intersect(lines[i], lines[j])
                if pt is not None:
                    ix, iy = pt
                    if 0 < ix < w and 0 < iy < h * 0.65:
                        intersections.append(pt)
        if intersections:
            xs = [p[0] for p in intersections]
            ys = [p[1] for p in intersections]
            self._vp = (int(np.median(xs)), int(np.median(ys)))
        elif self._vp is None:
            self._vp = (w // 2, int(h * 0.40))

    @staticmethod
    def _intersect(seg_a, seg_b):
        x1, y1, x2, y2 = seg_a
        x3, y3, x4, y4 = seg_b
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-6:
            return None
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        ix = x1 + t * (x2 - x1)
        iy = y1 + t * (y2 - y1)
        return (ix, iy)

    def _vote(self, current_frame_lines):
        all_recent = [seg for past in self._frame_history for seg in past]
        voted = []
        for seg in current_frame_lines:
            votes = sum(1 for other in all_recent
                        if other is not seg and self._lines_agree(seg, other))
            if votes >= self.VOTE_MIN:
                voted.append(seg)
        return voted

    @staticmethod
    def _lines_agree(a, b, pos_tol=35, angle_tol=12):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ma = ((ax1 + ax2) / 2, (ay1 + ay2) / 2)
        mb = ((bx1 + bx2) / 2, (by1 + by2) / 2)
        if np.hypot(ma[0] - mb[0], ma[1] - mb[1]) > pos_tol:
            return False
        ang_a = np.degrees(np.arctan2(ay2 - ay1, ax2 - ax1))
        ang_b = np.degrees(np.arctan2(by2 - by1, bx2 - bx1))
        diff  = abs(ang_a - ang_b) % 180
        return min(diff, 180 - diff) < angle_tol

    def _tolerance(self, cy, frame_h):
        roi_top = int(frame_h * self.ROI_TOP_RATIO)
        t = max(0.0, min(1.0, (cy - roi_top) / max(1, frame_h - roi_top)))
        return int(self.TOLERANCE_BASE + t * (self.TOLERANCE_NEAR - self.TOLERANCE_BASE))

    @staticmethod
    def _point_to_segment_dist(px, py, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return np.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0,
                ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        return np.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
