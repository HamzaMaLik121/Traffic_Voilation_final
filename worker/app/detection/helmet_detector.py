"""
Helmet Detection Module
Detects whether motorcycle riders are wearing helmets.
"""

import cv2
import numpy as np
from ultralytics import YOLO
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import HELMET_MODEL, HELMET_CONFIDENCE_THRESHOLD


RIDER_VEHICLE_CLASSES = {
    'motorcycle', 'motorbike', 'motor', 'bike',
    'bicycle', 'cycle', 'scooter', 'moped'
}


class HelmetDetector:
    def __init__(self, model_path=None):
        if model_path is None:
            model_path = HELMET_MODEL

        try:
            self.model = YOLO(str(model_path))
            print(f"✓ Loaded Helmet AI: {model_path}")
        except Exception as e:
            print(f"✗ FAILED TO LOAD HELMET AI! Please ensure best.pt is at: {model_path}")
            print(f"  Error: {e}")
            self.model = YOLO('yolov8n.pt')

        self.confidence_threshold = HELMET_CONFIDENCE_THRESHOLD
        self.classes = {0: 'no_helmet', 1: 'helmet'}
        self.min_iou = 0.10

    def detect_no_helmet_violation(self, frame, vehicle_detections):
        violations = []

        # Check if vehicle model has specific motorcycle classes or only generic 'vehicle'
        # When model is single-class ('vehicle'), treat ALL detected vehicles as potential
        # rider vehicles. The helmet model's IoU matching ensures only overlapping
        # detections (actual riders) trigger violations.
        rider_vehicles = [
            v for v in vehicle_detections
            if v.get('class_name', '').lower() in RIDER_VEHICLE_CLASSES
        ]

        # If no vehicles matched motorcycle classes, check ALL vehicles as potential
        # riders (handles single-class vehicle models that only detect 'vehicle')
        if not rider_vehicles and vehicle_detections:
            rider_vehicles = vehicle_detections

        results = self.model(frame, conf=self.confidence_threshold)

        no_helmet_detections = []
        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                label = self.classes.get(cls_id, 'unknown')
                if label != 'no_helmet':
                    continue
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                no_helmet_detections.append({
                    'bbox': [int(x1), int(y1), int(x2), int(y2)],
                    'confidence': float(box.conf[0])
                })

        already_flagged = set()
        for vehicle in rider_vehicles:
            v_bbox = vehicle['bbox']
            v_key = tuple(v_bbox)

            if v_key in already_flagged:
                continue

            for nd in no_helmet_detections:
                iou = self._iou(v_bbox, nd['bbox'])
                if iou >= self.min_iou:
                    violations.append({
                        'type': 'NO_HELMET',
                        'vehicle_bbox': v_bbox,
                        'vehicle_type': vehicle.get('class_name', 'motorcycle'),
                        'person_bbox': nd['bbox'],
                        'confidence': nd['confidence'],
                        'iou': round(iou, 3),
                    })
                    already_flagged.add(v_key)
                    break

        return violations

    def draw_violations(self, frame, violations):
        annotated_frame = frame.copy()

        for violation in violations:
            v_bbox = violation['vehicle_bbox']
            p_bbox = violation['person_bbox']
            conf  = violation['confidence']

            cv2.rectangle(annotated_frame,
                          (v_bbox[0], v_bbox[1]),
                          (v_bbox[2], v_bbox[3]),
                          (0, 0, 255), 3)

            cv2.rectangle(annotated_frame,
                          (p_bbox[0], p_bbox[1]),
                          (p_bbox[2], p_bbox[3]),
                          (0, 0, 200), 2)

            label = f"NO HELMET! {conf:.0%}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
            cv2.rectangle(annotated_frame,
                          (v_bbox[0], v_bbox[1] - th - 8),
                          (v_bbox[0] + tw, v_bbox[1]),
                          (0, 0, 255), -1)
            cv2.putText(annotated_frame, label,
                        (v_bbox[0], v_bbox[1] - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

        return annotated_frame

    @staticmethod
    def _iou(box1, box2):
        ax1, ay1, ax2, ay2 = box1
        bx1, by1, bx2, by2 = box2

        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)

        inter_w = max(0, ix2 - ix1)
        inter_h = max(0, iy2 - iy1)
        intersection = inter_w * inter_h

        if intersection == 0:
            return 0.0

        area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
        area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
        union = area_a + area_b - intersection

        return intersection / union if union > 0 else 0.0


if __name__ == "__main__":
    print("Helmet Detector initialized")
    detector = HelmetDetector()
