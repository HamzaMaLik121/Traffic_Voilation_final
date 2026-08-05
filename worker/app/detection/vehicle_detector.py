"""
Vehicle Detection Module using YOLOv8
Detects vehicles using BOTH the COCO pre-trained model AND the custom-trained model,
merging results for maximum detection coverage.

The COCO model (yolov8n.pt) provides reliable general vehicle detection. The custom
model supplements with specialized detections only when COCO returns nothing,
minimizing performance impact.
"""

import cv2
import numpy as np
from ultralytics import YOLO
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import VEHICLE_MODEL, CONFIDENCE_THRESHOLD, IOU_THRESHOLD, FALLBACK_VEHICLE_MODEL


# Vehicle classes from COCO — deliberately excludes 'person' (class 0) to avoid
# treating pedestrians as vehicles and causing false violation alerts.
COCO_VEHICLE_CLASSES = {
    1: 'bicycle',
    2: 'car',
    3: 'motorcycle',
    5: 'bus',
    7: 'truck',
}

CUSTOM_TARGET_NAMES = [
    'vehicle', 'car', 'motorcycle', 'bus', 'truck',
    'motorbike', 'auto-rickshaw', 'cycle', 'bicycle',
    'van', 'pickup', 'tractor', 'two_wheeler', 'rider',
    'scooter', 'moped',
]


def _iou(box1, box2):
    """Calculate IoU between two boxes [x1,y1,x2,y2]"""
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

    area1 = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area2 = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area1 + area2 - intersection

    return intersection / union if union > 0 else 0.0


def _is_duplicate(new_box, existing_detections, iou_thresh=0.5):
    """Check if a detection overlaps significantly with existing ones"""
    for det in existing_detections:
        if _iou(new_box, det['bbox']) > iou_thresh:
            return True
    return False


class VehicleDetector:
    """Vehicle detection using YOLOv8 with dual-model support (COCO + Custom)"""

    def __init__(self, model_path=None):
        if model_path is None:
            model_path = VEHICLE_MODEL

        # 1. Always load the COCO pre-trained model (yolov8n.pt) as primary detector
        try:
            self.coco_model = YOLO(FALLBACK_VEHICLE_MODEL)
            print(f"✓ Loaded COCO Vehicle AI: {FALLBACK_VEHICLE_MODEL}")
        except Exception as e:
            print(f"✗ FAILED TO LOAD COCO MODEL: {e}")
            self.coco_model = None

        # 2. Try to load the custom trained model as supplementary detector
        self.custom_model = None
        try:
            self.custom_model = YOLO(str(model_path))
            print(f"✓ Loaded Custom Vehicle AI: {model_path}")
        except Exception as e:
            print(f"ℹ Custom vehicle model not available, using COCO only: {e}")

        # Build vehicle class map from COCO classes
        self.vehicle_classes = dict(COCO_VEHICLE_CLASSES)

        # Add any custom model classes that match vehicle targets
        if self.custom_model:
            for idx, name in self.custom_model.names.items():
                if name.lower() in CUSTOM_TARGET_NAMES and idx not in self.vehicle_classes:
                    self.vehicle_classes[idx] = name

        print(f"  Monitoring vehicle classes: {self.vehicle_classes}")

        self.confidence_threshold = 0.15           # COCO model
        self.custom_confidence_threshold = 0.10    # Custom model (lower threshold)
        self.iou_threshold = IOU_THRESHOLD
        self._imgsz = 640
        self._custom_run_counter = 0               # Run custom model sparingly

    def detect(self, frame):
        """Run COCO model always; run custom model only when COCO finds nothing"""
        all_detections = []

        # 1. Run COCO model (primary)
        if self.coco_model:
            try:
                results = self.coco_model(
                    frame,
                    conf=self.confidence_threshold,
                    iou=self.iou_threshold,
                    imgsz=self._imgsz,
                    verbose=False
                )

                for result in results:
                    boxes = result.boxes
                    for box in boxes:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        cls_id = int(box.cls[0])
                        confidence = float(box.conf[0])

                        if cls_id in self.vehicle_classes:
                            detection = {
                                'bbox': [int(x1), int(y1), int(x2), int(y2)],
                                'class_id': cls_id,
                                'class_name': self.vehicle_classes[cls_id],
                                'confidence': confidence,
                                'source': 'coco'
                            }
                            all_detections.append(detection)
            except Exception as e:
                print(f"  [WARN] COCO model detection failed: {e}")

        # 2. Only run custom model when COCO found few or no vehicles
        #    Also throttle: run custom model every 3rd detection cycle max
        self._custom_run_counter += 1
        should_run_custom = (
            self.custom_model is not None
            and self._custom_run_counter % 3 == 0
        )

        if should_run_custom or (self.custom_model and len(all_detections) == 0):
            try:
                results = self.custom_model(
                    frame,
                    conf=self.custom_confidence_threshold,
                    iou=self.iou_threshold,
                    imgsz=self._imgsz,
                    verbose=False
                )

                for result in results:
                    boxes = result.boxes
                    for box in boxes:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        cls_id = int(box.cls[0])
                        confidence = float(box.conf[0])
                        new_bbox = [int(x1), int(y1), int(x2), int(y2)]

                        class_name = self.custom_model.names.get(cls_id, 'vehicle')

                        # Only add non-duplicate detections
                        if not _is_duplicate(new_bbox, all_detections):
                            detection = {
                                'bbox': new_bbox,
                                'class_id': cls_id,
                                'class_name': class_name,
                                'confidence': confidence,
                                'source': 'custom'
                            }
                            all_detections.append(detection)
            except Exception as e:
                print(f"  [WARN] Custom model detection failed: {e}")

        # Sort by confidence (highest first) for consistent behavior
        all_detections.sort(key=lambda d: d['confidence'], reverse=True)

        return all_detections

    def draw_detections(self, frame, detections):
        """Draw bounding boxes with source-aware colors (green=COCO, blue=custom)"""
        annotated_frame = frame.copy()

        for det in detections:
            x1, y1, x2, y2 = det['bbox']
            class_name = det['class_name']
            confidence = det['confidence']

            color = (0, 255, 0) if det.get('source') == 'coco' else (255, 200, 0)
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)

            label = f"{class_name}: {confidence:.2f}"
            cv2.putText(annotated_frame, label, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        return annotated_frame


if __name__ == "__main__":
    print("Testing Vehicle Detector...")
    detector = VehicleDetector()
    test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = detector.detect(test_frame)
    print(f"Detected {len(detections)} vehicles")
