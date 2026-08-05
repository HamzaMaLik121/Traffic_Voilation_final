"""
Illegal U-Turn Detection Module
Reuses vehicle position history to detect 180-degree direction reversals
"""

import numpy as np
from collections import defaultdict, deque
from pathlib import Path
import cv2
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))


class UTurnDetector:
    def __init__(self,
                 angle_threshold=168,
                 history_length=25,
                 match_distance=100,
                 min_displacement=50,
                 min_half_movement=20):
        self.angle_threshold   = angle_threshold
        self.history_length    = history_length
        self.match_distance    = match_distance
        self.min_displacement  = min_displacement
        self.min_half_movement = min_half_movement
        self._cooldown = {}
        self._COOLDOWN_FRAMES = 90

        self.tracks = {}
        self.last_bbox = {}
        self.stale_count = defaultdict(int)
        self.flagged = set()
        self.track_age = {}
        self.had_gap = set()
        self._MIN_AGE = 20

        self._next_id = 0

    def detect_uturn_violations(self, vehicles, frame_number):
        self._update_tracks(vehicles)
        self._cleanup_stale(frame_number)

        violations = []
        for vid, history in self.tracks.items():
            if vid in self.flagged:
                cd = self._cooldown.get(vid, 0)
                if frame_number - cd < self._COOLDOWN_FRAMES:
                    continue
                else:
                    self.flagged.discard(vid)
            if vid in self.had_gap:
                continue
            if self.track_age.get(vid, 0) < self._MIN_AGE:
                continue
            if len(history) < self.history_length // 2:
                continue
            if self._is_uturn(list(history)):
                violations.append({
                    'type':         'ILLEGAL_UTURN',
                    'vehicle_bbox': self.last_bbox.get(vid, [0, 0, 0, 0]),
                    'vehicle_type': 'vehicle',
                    'confidence':   0.75,
                    'vehicle_id':   vid,
                })
                self.flagged.add(vid)
                self._cooldown[vid] = frame_number

        return violations

    def draw_violations(self, frame, violations):
        annotated = frame.copy()
        for v in violations:
            x1, y1, x2, y2 = v['vehicle_bbox']
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 0, 255), 3)
            label = "ILLEGAL U-TURN"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(annotated, (x1, y1 - th - 8), (x1 + tw, y1), (255, 0, 255), -1)
            cv2.putText(annotated, label, (x1, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        return annotated

    def _update_tracks(self, vehicles):
        matched_ids = set()
        for vehicle in vehicles:
            x1, y1, x2, y2 = vehicle['bbox']
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            vid = self._match_vehicle(cx, cy)
            matched_ids.add(vid)
            if vid not in self.tracks:
                self.tracks[vid] = deque(maxlen=self.history_length)
            self.tracks[vid].append((cx, cy))
            self.last_bbox[vid]  = vehicle['bbox']
            self.stale_count[vid] = 0
            self.track_age[vid]  = self.track_age.get(vid, 0) + 1
        for vid in list(self.tracks.keys()):
            if vid not in matched_ids:
                old_stale = self.stale_count[vid]
                self.stale_count[vid] += 1
                if old_stale == 0:
                    self.had_gap.add(vid)
                self.track_age[vid] = 0

    def _match_vehicle(self, cx, cy):
        best_id = None
        best_dist = self.match_distance
        for vid, history in self.tracks.items():
            if not history:
                continue
            lx, ly = history[-1]
            dist = np.hypot(cx - lx, cy - ly)
            if dist < best_dist:
                best_dist = dist
                best_id = vid
        if best_id is None:
            best_id = self._next_id
            self._next_id += 1
        return best_id

    def _is_uturn(self, positions):
        if len(positions) < 4:
            return False
        total_disp = np.hypot(positions[-1][0] - positions[0][0],
                              positions[-1][1] - positions[0][1])
        if total_disp < self.min_displacement:
            return False
        mid = len(positions) // 2
        first_half  = positions[:mid]
        second_half = positions[mid:]
        first_disp  = np.hypot(first_half[-1][0]  - first_half[0][0],
                               first_half[-1][1]  - first_half[0][1])
        second_disp = np.hypot(second_half[-1][0] - second_half[0][0],
                               second_half[-1][1] - second_half[0][1])
        if first_disp < self.min_half_movement or \
           second_disp < self.min_half_movement:
            return False
        vec1 = self._avg_heading(first_half)
        vec2 = self._avg_heading(second_half)
        if vec1 is None or vec2 is None:
            return False
        angle = self._angle_between(vec1, vec2)
        if angle < self.angle_threshold:
            return False
        dy1 = first_half[-1][1]  - first_half[0][1]
        dy2 = second_half[-1][1] - second_half[0][1]
        if dy1 * dy2 >= 0:
            return False
        if abs(dy1) < 8 or abs(dy2) < 8:
            return False
        return True

    @staticmethod
    def _avg_heading(positions):
        if len(positions) < 2:
            return None
        vectors = [(positions[i][0] - positions[i-1][0],
                    positions[i][1] - positions[i-1][1])
                   for i in range(1, len(positions))]
        avg_x = np.mean([v[0] for v in vectors])
        avg_y = np.mean([v[1] for v in vectors])
        mag = np.hypot(avg_x, avg_y)
        if mag < 1e-6:
            return None
        return (avg_x / mag, avg_y / mag)

    @staticmethod
    def _angle_between(v1, v2):
        dot = np.clip(v1[0] * v2[0] + v1[1] * v2[1], -1.0, 1.0)
        return np.degrees(np.arccos(dot))

    def _cleanup_stale(self, frame_number, max_stale=30):
        stale_ids = [vid for vid, count in self.stale_count.items()
                     if count > max_stale]
        for vid in stale_ids:
            self.tracks.pop(vid, None)
            self.last_bbox.pop(vid, None)
            self.stale_count.pop(vid, None)
            self.track_age.pop(vid, None)
            self.had_gap.discard(vid)
            self.flagged.discard(vid)
