"""
Universal Lane Detector -- VP-geometry based, zero downloads.
Works for ANY camera angle using vanishing-point geometry.
"""

import math
import cv2
import numpy as np
from collections import defaultdict, deque
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))


class PolyLaneDetector:
    ROI_TOP_RATIO  = 0.45
    TRAP_INSET     = 0.05
    MIN_LEN        = 50
    MIN_SLOPE      = 0.15
    MAX_SLOPE      = 20.0
    VP_EMA         = 0.10
    LANE_EMA       = 0.18
    HISTORY        = 6
    VIOL_THRESHOLD = 10

    LEFT_COLOR  = (  0, 220, 255)
    RIGHT_COLOR = ( 80, 255,  80)
    FILL_COLOR  = (255, 200,   0)
    FILL_ALPHA  = 0.14

    def __init__(self, viol_threshold=None):
        self.viol_threshold = viol_threshold or self.VIOL_THRESHOLD
        self._vp          = None
        self._vp_history  = deque(maxlen=20)
        self._left_ema    = None
        self._right_ema   = None
        self._left_hist   = deque(maxlen=self.HISTORY)
        self._right_hist  = deque(maxlen=self.HISTORY)
        self._cross_cnt   = defaultdict(int)
        self._last_left   = []
        self._last_right  = []
        self._frame_h     = 720
        self._frame_w     = 1280

    def detect_lanes(self, frame, vehicles=None):
        self._frame_h, self._frame_w = frame.shape[:2]
        h, w = self._frame_h, self._frame_w
        roi_top = int(h * self.ROI_TOP_RATIO)

        inset    = int(w * self.TRAP_INSET)
        trap_pts = np.array([[inset,  roi_top],
                             [w-inset, roi_top],
                             [w,       h],
                             [0,       h]], dtype=np.int32)
        trap_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(trap_mask, [trap_pts], 255)

        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges   = cv2.Canny(blurred, 50, 150)

        if vehicles:
            for v in vehicles:
                x1, y1, x2, y2 = v['bbox']
                edges[max(0, y1-5):min(h, y2+10),
                      max(0, x1-5):min(w, x2+5)] = 0

        edges = cv2.bitwise_and(edges, trap_mask)

        raw = cv2.HoughLinesP(edges, 1, np.pi / 180,
                              threshold=35,
                              minLineLength=self.MIN_LEN,
                              maxLineGap=60)

        valid_lines = []
        if raw is not None:
            for seg in raw:
                x1, y1, x2, y2 = seg[0]
                if x2 == x1:
                    continue
                slope = abs((y2 - y1) / (x2 - x1))
                if slope < self.MIN_SLOPE or slope > self.MAX_SLOPE:
                    continue
                length = math.hypot(x2-x1, y2-y1)
                if length < self.MIN_LEN:
                    continue
                valid_lines.append((x1, y1, x2, y2, length))

        self._update_vp(valid_lines, w, h)
        vp_x = self._vp[0] if self._vp else w // 2

        left_pts, left_wts   = [], []
        right_pts, right_wts = [], []

        for (x1, y1, x2, y2, length) in valid_lines:
            x_base = self._x_at_y(x1, y1, x2, y2, h)
            if x_base is None:
                continue
            if x_base < vp_x:
                left_pts.extend([(x1, y1), (x2, y2)])
                left_wts.extend([length, length])
            else:
                right_pts.extend([(x1, y1), (x2, y2)])
                right_wts.extend([length, length])

        self._last_left  = self._fit(left_pts,  left_wts,  'left',  h, w)
        self._last_right = self._fit(right_pts, right_wts, 'right', h, w)

        return self._last_left, self._last_right

    def detect_lane_violations(self, frame, vehicles):
        left, right = self.detect_lanes(frame, vehicles)
        h = frame.shape[0]
        viols = []

        segments = []
        for pts in (left, right):
            for i in range(len(pts) - 1):
                segments.append((*pts[i], *pts[i+1]))

        for vehicle in vehicles:
            x1, y1, x2, y2 = vehicle['bbox']
            cx  = (x1 + x2) // 2
            cy  = y2
            vid = f"{(cx//80)*80}_{(cy//80)*80}"

            t   = max(0.0, min(1.0, cy / h))
            tol = int(14 + t * 14)

            on_line = any(self._dist(cx, cy, *s) < tol for s in segments)

            if on_line:
                self._cross_cnt[vid] += 1
            else:
                self._cross_cnt[vid] = max(0, self._cross_cnt[vid] - 1)

            if self._cross_cnt[vid] >= self.viol_threshold:
                viols.append({
                    'type':         'LANE_VIOLATION',
                    'vehicle_bbox': vehicle['bbox'],
                    'vehicle_type': vehicle.get('class_name', 'vehicle'),
                    'confidence':   vehicle.get('confidence', 0.5),
                })
                self._cross_cnt[vid] = 0

        return viols

    def draw_lanes(self, frame, lanes=None):
        left  = self._last_left
        right = self._last_right

        if len(left) >= 2 and len(right) >= 2:
            poly = np.array(left + list(reversed(right)), dtype=np.int32)
            over = frame.copy()
            cv2.fillPoly(over, [poly], self.FILL_COLOR)
            cv2.addWeighted(over, self.FILL_ALPHA, frame,
                            1 - self.FILL_ALPHA, 0, frame)

        for i in range(len(left) - 1):
            cv2.line(frame, left[i], left[i+1], self.LEFT_COLOR, 3)
        for i in range(len(right) - 1):
            cv2.line(frame, right[i], right[i+1], self.RIGHT_COLOR, 3)

        if self._vp:
            cv2.circle(frame, self._vp, 5, (255, 255, 0), -1)

        return frame

    def draw_violations(self, frame, violations):
        for v in violations:
            x1, y1, x2, y2 = v['vehicle_bbox']
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 3)
            label = "LANE VIOLATION"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (x1, y1-th-8), (x1+tw, y1), (0, 165, 255), -1)
            cv2.putText(frame, label, (x1, y1-4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        return frame

    def _update_vp(self, lines, w, h):
        if len(lines) < 2:
            if self._vp is None:
                self._vp = (w // 2, int(h * 0.40))
            return
        pts = []
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                pt = self._intersect(lines[i][:4], lines[j][:4])
                if pt is None:
                    continue
                px, py = pt
                if 0 < px < w and 0 < py < h * 0.65:
                    pts.append((px, py))
        if not pts:
            if self._vp is None:
                self._vp = (w // 2, int(h * 0.40))
            return
        new_vp_x = float(np.median([p[0] for p in pts]))
        new_vp_y = float(np.median([p[1] for p in pts]))
        if self._vp is None:
            self._vp = (int(new_vp_x), int(new_vp_y))
        else:
            a = self.VP_EMA
            self._vp = (int(a * new_vp_x + (1-a) * self._vp[0]),
                        int(a * new_vp_y + (1-a) * self._vp[1]))

    def _fit(self, pts, wts, side, h, w):
        roi_top = int(h * self.ROI_TOP_RATIO)
        if len(pts) >= 4 and len(wts) == len(pts):
            ys = np.array([p[1] for p in pts], dtype=np.float64)
            xs = np.array([p[0] for p in pts], dtype=np.float64)
            ws = np.array(wts, dtype=np.float64)
            ws = ws / (ws.sum() + 1e-9)
            try:
                new_poly = np.polyfit(ys, xs, 1, w=ws)
            except Exception:
                new_poly = None
            hist = self._left_hist if side == 'left' else self._right_hist
            if new_poly is not None:
                hist.append(new_poly)
            if hist:
                poly = np.mean(hist, axis=0)
                ema  = self._left_ema if side == 'left' else self._right_ema
                poly = self._ema_poly(ema, poly)
                if side == 'left':
                    self._left_ema  = poly
                else:
                    self._right_ema = poly
            else:
                poly = self._left_ema if side == 'left' else self._right_ema
        else:
            poly = self._left_ema if side == 'left' else self._right_ema
        if poly is None:
            return []
        y_vals = np.linspace(h, roi_top, 25).astype(int)
        x_vals = np.polyval(poly, y_vals).astype(int)
        x_vals = np.clip(x_vals, 0, w - 1)
        return [(int(x), int(y)) for x, y in zip(x_vals, y_vals)]

    def _ema_poly(self, prev, new):
        if new is None:
            return prev
        if prev is None:
            return np.asarray(new, dtype=np.float64)
        a = self.LANE_EMA
        return a * np.asarray(new, dtype=np.float64) + \
               (1 - a) * np.asarray(prev, dtype=np.float64)

    @staticmethod
    def _x_at_y(x1, y1, x2, y2, target_y):
        dy = y2 - y1
        if abs(dy) < 1:
            return None
        t = (target_y - y1) / dy
        return x1 + t * (x2 - x1)

    @staticmethod
    def _intersect(seg_a, seg_b):
        x1, y1, x2, y2 = seg_a
        x3, y3, x4, y4 = seg_b
        denom = (x1-x2)*(y3-y4) - (y1-y2)*(x3-x4)
        if abs(denom) < 1e-6:
            return None
        t = ((x1-x3)*(y3-y4) - (y1-y3)*(x3-x4)) / denom
        return (x1 + t*(x2-x1), y1 + t*(y2-y1))

    @staticmethod
    def _dist(px, py, x1, y1, x2, y2):
        dx, dy = x2-x1, y2-y1
        if dx == 0 and dy == 0:
            return math.hypot(px-x1, py-y1)
        t = max(0., min(1., ((px-x1)*dx+(py-y1)*dy)/(dx*dx+dy*dy)))
        return math.hypot(px-(x1+t*dx), py-(y1+t*dy))
