"""
YOLOP Lane Detection using ONNX model.
Model path is now driven by config (env-var-friendly).
"""

import cv2
import numpy as np
from pathlib import Path
import sys
import onnxruntime as ort

sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import LANE_MODEL

LANE_COLORS = [
    (0,  220, 255),
    (80, 255, 80),
    (255, 80, 200),
    (255, 180, 0),
    (80,  80, 255),
    (255, 255, 80),
]

class YolopLaneDetector:
    FILL_ALPHA      = 0.12
    VIOL_THRESHOLD  = 10
    MIN_LANE_PIXELS = 15
    PEAK_MIN_RATIO  = 0.08
    PEAK_MIN_SEP_RATIO = 0.08

    def __init__(self, model_path=None, viol_threshold=None):
        self.viol_threshold = viol_threshold or self.VIOL_THRESHOLD

        if model_path is None:
            model_path = LANE_MODEL

        if not Path(model_path).exists():
            raise FileNotFoundError(
                f"YOLOP ONNX model not found at {model_path}\n"
                "Please download yolop-640-640.onnx and place it there."
            )

        print(f"  [INFO] Loading YOLOP ONNX model from {model_path}...")
        self.session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        print("  [OK] YOLOP ONNX loaded successfully")

        self._all_lanes: list = []
        self._cross_cnt: dict = {}
        self._last_left:  list = []
        self._last_right: list = []

    def detect_lanes(self, frame, vehicles=None):
        h, w = frame.shape[:2]

        img = cv2.resize(frame, (640, 640))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img -= np.array([0.485, 0.456, 0.406])
        img /= np.array([0.229, 0.224, 0.225])
        img = np.expand_dims(np.transpose(img, (2, 0, 1)), axis=0)
        self._frame_w = w
        self._frame_h = h

        outputs = self.session.run(None, {self.input_name: img})
        ll_seg  = outputs[2]

        ll_mask = (np.argmax(ll_seg[0], axis=0) == 1).astype(np.uint8)

        kernel  = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 25))
        ll_mask = cv2.morphologyEx(ll_mask, cv2.MORPH_CLOSE, kernel)

        ll_mask = cv2.resize(ll_mask, (w, h), interpolation=cv2.INTER_NEAREST)

        self._all_lanes = self._extract_all_lanes(ll_mask, w, h)

        if len(self._all_lanes) >= 2:
            self._last_left  = self._all_lanes[0]
            self._last_right = self._all_lanes[-1]
        elif len(self._all_lanes) == 1:
            self._last_left  = self._all_lanes[0]
            self._last_right = []
        else:
            self._last_left  = []
            self._last_right = []

        return self._last_left, self._last_right

    def detect_lane_violations(self, frame, vehicles):
        viols    = []
        segments = []
        h        = frame.shape[0]

        for lane in self._all_lanes:
            for i in range(len(lane) - 1):
                segments.append((*lane[i], *lane[i + 1]))

        for vehicle in vehicles:
            x1, y1, x2, y2 = vehicle["bbox"]
            cx  = (x1 + x2) // 2
            cy  = y2
            vid = f"{(cx // 80) * 80}_{(cy // 80) * 80}"

            tol      = int(14 + max(0.0, min(1.0, cy / h)) * 14)
            on_line  = False
            for (sx1, sy1, sx2, sy2) in segments:
                dx, dy = sx2 - sx1, sy2 - sy1
                if dx == 0 and dy == 0:
                    continue
                t      = max(0.0, min(1.0, ((cx-sx1)*dx + (cy-sy1)*dy) / (dx*dx + dy*dy)))
                proj_x = sx1 + t * dx
                proj_y = sy1 + t * dy
                if ((cx - proj_x) ** 2 + (cy - proj_y) ** 2) ** 0.5 < tol:
                    on_line = True
                    break

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
        n = len(self._all_lanes)
        for idx, lane in enumerate(self._all_lanes):
            if len(lane) < 2:
                continue
            color = LANE_COLORS[idx % len(LANE_COLORS)]
            if idx < n - 1:
                next_lane = self._all_lanes[idx + 1]
                if len(next_lane) >= 2:
                    poly = np.array(lane + list(reversed(next_lane)), dtype=np.int32)
                    over = frame.copy()
                    fill = LANE_COLORS[(idx + 2) % len(LANE_COLORS)]
                    cv2.fillPoly(over, [poly], fill)
                    cv2.addWeighted(over, self.FILL_ALPHA, frame, 1 - self.FILL_ALPHA, 0, frame)
            for i in range(len(lane) - 1):
                cv2.line(frame, lane[i], lane[i + 1], color, 3, cv2.LINE_AA)
        return frame

    def draw_violations(self, frame, violations):
        for v in violations:
            x1, y1, x2, y2 = v["vehicle_bbox"]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 3)
            cv2.putText(frame, "LANE VIOLATION", (x1, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        return frame

    def _extract_all_lanes(self, mask, w, h):
        roi_top = int(h * 0.40)
        roi     = mask[roi_top:, :]

        hist = roi.sum(axis=0).astype(np.float32)
        if hist.max() == 0:
            return []

        smooth_px = max(9, w // 90)
        kernel_1d = np.ones(smooth_px, dtype=np.float32) / smooth_px
        hist = np.convolve(hist, kernel_1d, mode="same")

        min_sep = max(60, int(w * self.PEAK_MIN_SEP_RATIO))
        peak_threshold = hist.max() * self.PEAK_MIN_RATIO
        peaks = self._find_histogram_peaks(hist, peak_threshold, min_sep)

        if not peaks:
            return []

        lanes = []
        margin = max(20, w // 30)
        y_all, x_all = np.where(mask > 0)

        for peak_x in peaks:
            in_window = (x_all >= peak_x - margin) & (x_all <= peak_x + margin)
            lx = x_all[in_window]
            ly = y_all[in_window]
            if len(lx) < self.MIN_LANE_PIXELS:
                continue
            pts = self._fit_poly(lx, ly, h, w)
            if pts:
                lanes.append(pts)

        lanes.sort(key=lambda pts: pts[0][0] if pts else 0)
        return lanes

    @staticmethod
    def _find_histogram_peaks(hist, threshold, min_sep=30):
        peaks = []
        n     = len(hist)
        i     = 0
        while i < n:
            if hist[i] < threshold:
                i += 1
                continue
            j = i
            while j < n and hist[j] >= threshold:
                j += 1
            peak_x = i + int(np.argmax(hist[i:j]))
            if not peaks or (peak_x - peaks[-1]) >= min_sep:
                peaks.append(peak_x)
            else:
                if hist[peak_x] > hist[peaks[-1]]:
                    peaks[-1] = peak_x
            i = j
        return peaks

    @staticmethod
    def _fit_poly(x, y, h, w=10000):
        if len(x) < 15:
            return []
        try:
            poly   = np.polyfit(y, x, 1)
            y_vals = np.linspace(h, int(h * 0.35), 20).astype(int)
            x_vals = np.polyval(poly, y_vals)

            bottom = x_vals[:8]
            if bottom.min() < -w * 0.15 or bottom.max() > w * 1.15:
                return []

            x_vals = np.clip(x_vals, 0, w - 1).astype(int)
            return [(int(px), int(py)) for px, py in zip(x_vals, y_vals)]
        except (np.linalg.LinAlgError, ValueError):
            return []
