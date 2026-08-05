"""
Speed Estimation Module
Estimates vehicle speed using optical flow and tracking
"""

import cv2
import numpy as np
from collections import defaultdict
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import SPEED_LIMIT_KMH, SPEED_DETECTION_THRESHOLD, FRAME_RATE, PIXEL_TO_METER_RATIO, FRAME_SKIP


class SpeedEstimator:
    def __init__(self, speed_limit=SPEED_LIMIT_KMH,
                 detection_threshold=SPEED_DETECTION_THRESHOLD,
                 fps=FRAME_RATE):
        self.speed_limit = speed_limit
        self.detection_threshold = detection_threshold
        self.fps = fps
        self.pixel_to_meter = PIXEL_TO_METER_RATIO

        self.vehicle_tracks = defaultdict(list)
        self.vehicle_speeds = {}
        self.next_vehicle_id = 0
    
    def estimate_speed(self, vehicle_detections, frame_number):
        speed_violations = []
        
        for detection in vehicle_detections:
            bbox = detection['bbox']
            center = self._get_bbox_center(bbox)
            
            vehicle_id = self._match_or_create_track(center, bbox)
            
            self.vehicle_tracks[vehicle_id].append({
                'frame': frame_number,
                'center': center,
                'bbox': bbox
            })
            
            if len(self.vehicle_tracks[vehicle_id]) >= 10:
                speed = self._calculate_speed(vehicle_id)
                self.vehicle_speeds[vehicle_id] = speed
                
                if speed > self.detection_threshold:
                    speed_violations.append({
                        'type': 'OVER_SPEED',
                        'vehicle_id': vehicle_id,
                        'vehicle_bbox': bbox,
                        'vehicle_type': detection.get('class_name', 'vehicle'),
                        'speed': round(speed, 1),
                        'speed_limit': self.speed_limit,
                        'confidence': detection['confidence']
                    })
        
        self._cleanup_old_tracks(frame_number)
        return speed_violations
    
    def _get_bbox_center(self, bbox):
        x1, y1, x2, y2 = bbox
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        return (center_x, center_y)
    
    def _match_or_create_track(self, center, bbox):
        min_distance = float('inf')
        matched_id = None
        
        for vehicle_id, track in self.vehicle_tracks.items():
            if len(track) > 0:
                last_center = track[-1]['center']
                distance = np.sqrt((center[0] - last_center[0])**2 + 
                                 (center[1] - last_center[1])**2)
                
                if distance < 100 and distance < min_distance:
                    min_distance = distance
                    matched_id = vehicle_id
        
        if matched_id is None:
            matched_id = self.next_vehicle_id
            self.next_vehicle_id += 1
        
        return matched_id
    
    def _calculate_speed(self, vehicle_id):
        track = self.vehicle_tracks[vehicle_id]
        
        if len(track) < 2:
            return 0
        
        recent_track = track[-10:]
        
        total_distance_pixels = 0
        for i in range(1, len(recent_track)):
            prev_center = recent_track[i-1]['center']
            curr_center = recent_track[i]['center']
            
            distance = np.sqrt((curr_center[0] - prev_center[0])**2 + 
                             (curr_center[1] - prev_center[1])**2)
            total_distance_pixels += distance
        
        total_distance_meters = total_distance_pixels * self.pixel_to_meter
        
        frames_elapsed = len(recent_track) - 1
        effective_fps = self.fps / (FRAME_SKIP + 1)
        time_seconds = frames_elapsed / effective_fps

        if time_seconds == 0:
            return 0

        speed_ms = total_distance_meters / time_seconds
        speed_kmh = speed_ms * 3.6

        return speed_kmh
    
    def _cleanup_old_tracks(self, current_frame, max_age=30):
        tracks_to_remove = []
        
        for vehicle_id, track in self.vehicle_tracks.items():
            if len(track) > 0:
                last_frame = track[-1]['frame']
                if current_frame - last_frame > max_age:
                    tracks_to_remove.append(vehicle_id)
        
        for vehicle_id in tracks_to_remove:
            del self.vehicle_tracks[vehicle_id]
            if vehicle_id in self.vehicle_speeds:
                del self.vehicle_speeds[vehicle_id]
    
    def draw_speed_violations(self, frame, violations):
        annotated_frame = frame.copy()

        for violation in violations:
            bbox = violation['vehicle_bbox']
            speed = violation['speed']
            limit = violation['speed_limit']

            cv2.rectangle(annotated_frame,
                         (bbox[0], bbox[1]),
                         (bbox[2], bbox[3]),
                         (0, 0, 255), 3)

            text = f"SPEEDING: {speed:.1f} km/h (Limit: {limit})"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(annotated_frame,
                          (bbox[0], bbox[1] - th - 8),
                          (bbox[0] + tw, bbox[1]),
                          (0, 0, 255), -1)
            cv2.putText(annotated_frame, text,
                       (bbox[0], bbox[1] - 4),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        return annotated_frame

    def draw_speed_info(self, frame, vehicle_detections):
        annotated = frame.copy()
        for detection in vehicle_detections:
            bbox = detection['bbox']
            center = self._get_bbox_center(bbox)

            vid = None
            best_dist = 60
            for vehicle_id, track in self.vehicle_tracks.items():
                if track:
                    lx, ly = track[-1]['center']
                    d = ((center[0] - lx) ** 2 + (center[1] - ly) ** 2) ** 0.5
                    if d < best_dist:
                        best_dist = d
                        vid = vehicle_id

            speed = self.vehicle_speeds.get(vid, 0)
            if speed > 0:
                color = (0, 0, 255) if speed > self.speed_limit else (0, 255, 100)
                label = f"{speed:.0f} km/h"
                x1, y1, x2, y2 = bbox
                cv2.putText(annotated, label, (x1, y2 + 18),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        return annotated
