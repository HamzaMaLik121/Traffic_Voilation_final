"""
Traffic Light Detection Module
Detects traffic lights and determines their state (red/yellow/green)
"""

import cv2
import numpy as np
from ultralytics import YOLO
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import TRAFFIC_LIGHT_MODEL


class TrafficLightDetector:
    def __init__(self, model_path=None):
        if model_path is None:
            model_path = TRAFFIC_LIGHT_MODEL
        
        try:
            self.model = YOLO(str(model_path))
            print(f"✓ Loaded Traffic Light AI: {model_path}")
        except Exception as e:
            print(f"✗ FAILED TO LOAD TRAFFIC LIGHT AI! Please ensure best.pt is at: {model_path}")
            print(f"  Error: {e}")
            self.model = YOLO('yolov8n.pt')
            
        self.confidence_threshold = 0.20
        self.classes = {0: 'red', 1: 'yellow', 2: 'green'}
        self._rl_cooldown = {}
        self._frame_counter = 0
    
    def detect_traffic_lights(self, frame):
        results = self.model(frame, conf=self.confidence_threshold)
        
        traffic_lights = []
        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                state = self.classes.get(cls_id, 'unknown')
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                
                traffic_lights.append({
                    'bbox': [int(x1), int(y1), int(x2), int(y2)],
                    'state': state,
                    'confidence': float(box.conf[0])
                })
        
        return traffic_lights
    
    def detect_red_light_violation(self, frame, traffic_lights, vehicle_detections):
        violations = []
        red_lights = [tl for tl in traffic_lights if tl['state'] == 'red']

        if not red_lights:
            return violations

        frame_height = frame.shape[0]
        stop_line_y  = int(frame_height * 0.70)

        for vehicle in vehicle_detections:
            v_bbox  = vehicle['bbox']
            v_bot   = v_bbox[3]
            v_cx    = (v_bbox[0] + v_bbox[2]) // 2

            if v_bot <= stop_line_y:
                continue

            for red_light in red_lights:
                tl_bbox = red_light['bbox']
                tl_cx   = (tl_bbox[0] + tl_bbox[2]) // 2

                if abs(tl_cx - v_cx) > 120:
                    continue

                vid = f"{(v_cx // 100) * 100}_{(v_bot // 100) * 100}"
                last = self._rl_cooldown.get(vid, -999)
                if self._frame_counter - last < 30:
                    continue

                self._rl_cooldown[vid] = self._frame_counter

                violations.append({
                    'type':               'RED_LIGHT',
                    'vehicle_bbox':       v_bbox,
                    'traffic_light_bbox': tl_bbox,
                    'confidence':         vehicle.get('confidence', 0.8),
                })

        self._frame_counter += 1
        return violations
    
    def draw_traffic_lights(self, frame, traffic_lights):
        annotated_frame = frame.copy()
        
        for tl in traffic_lights:
            bbox = tl['bbox']
            state = tl['state']
            
            color_map = {
                'red': (0, 0, 255),
                'yellow': (0, 255, 255),
                'green': (0, 255, 0),
                'unknown': (128, 128, 128)
            }
            
            color = color_map.get(state, (128, 128, 128))
            
            cv2.rectangle(annotated_frame, 
                         (bbox[0], bbox[1]), 
                         (bbox[2], bbox[3]), 
                         color, 2)
            
            cv2.putText(annotated_frame, state.upper(), 
                       (bbox[0], bbox[1] - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        
        return annotated_frame


if __name__ == "__main__":
    print("Traffic Light Detector initialized")
    detector = TrafficLightDetector()
