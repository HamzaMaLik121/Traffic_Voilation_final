"""
Violation Processor
Main processing pipeline that integrates all detection modules
"""

import cv2
import numpy as np
from datetime import datetime
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))  # -> worker/

from app.detection.vehicle_detector import VehicleDetector
from app.detection.helmet_detector import HelmetDetector
from app.detection.traffic_light_detector import TrafficLightDetector
from app.detection.speed_estimator import SpeedEstimator
from app.lpr.plate_recognizer import LicensePlateRecognizer
from app.db.database import ViolationDatabase
from config.config import SAVE_EVIDENCE, OUTPUT_DIR, EVIDENCE_FORMAT


class ViolationProcessor:
    def __init__(self, use_gpu=False):
        print("Initializing Violation Detection System...")
        
        self.vehicle_detector = VehicleDetector()
        self.helmet_detector = HelmetDetector()
        self.traffic_light_detector = TrafficLightDetector()
        self.speed_estimator = SpeedEstimator()
        self.plate_recognizer = LicensePlateRecognizer(use_gpu=use_gpu)
        
        self.database = ViolationDatabase()
        
        self.evidence_dir = OUTPUT_DIR / "evidence"
        self.violations_dir = OUTPUT_DIR / "violations"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.violations_dir.mkdir(parents=True, exist_ok=True)
        
        print("✓ Violation Detection System ready")
    
    def process_frame(self, frame, frame_number, video_path=None):
        results = {
            'frame_number': frame_number,
            'violations': [],
            'detections': {
                'vehicles': [],
                'traffic_lights': [],
                'plates': []
            }
        }
        
        vehicle_detections = self.vehicle_detector.detect(frame)
        results['detections']['vehicles'] = vehicle_detections
        
        traffic_lights = self.traffic_light_detector.detect_traffic_lights(frame)
        results['detections']['traffic_lights'] = traffic_lights
        
        helmet_violations = self.helmet_detector.detect_no_helmet_violation(
            frame, vehicle_detections
        )
        
        red_light_violations = self.traffic_light_detector.detect_red_light_violation(
            frame, traffic_lights, vehicle_detections
        )
        
        speed_violations = self.speed_estimator.estimate_speed(
            vehicle_detections, frame_number
        )
        
        all_violations = helmet_violations + red_light_violations + speed_violations
        
        for violation in all_violations:
            vehicle_bbox = violation.get('vehicle_bbox')
            
            if vehicle_bbox:
                plate_info = self.plate_recognizer.detect_and_read_plate(
                    frame, vehicle_bbox
                )
                
                if plate_info:
                    violation['license_plate'] = plate_info['text']
                    violation['plate_confidence'] = plate_info['confidence']
                    results['detections']['plates'].append(plate_info)
                else:
                    violation['license_plate'] = None
                    violation['plate_confidence'] = 0.0
                
                if SAVE_EVIDENCE:
                    evidence_path = self._save_evidence(
                        frame, violation, frame_number
                    )
                    violation['evidence_path'] = str(evidence_path)
                
                violation_id = self._record_violation(
                    violation, frame_number, video_path
                )
                violation['database_id'] = violation_id
        
        results['violations'] = all_violations
        return results
    
    def _save_evidence(self, frame, violation, frame_number):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        violation_type = violation['type']
        filename = f"{violation_type}_{timestamp}_frame{frame_number}.{EVIDENCE_FORMAT}"
        evidence_path = self.evidence_dir / filename
        
        bbox = violation.get('vehicle_bbox')
        if bbox:
            x1, y1, x2, y2 = bbox
            h, w = frame.shape[:2]
            x1 = max(0, x1 - 50)
            y1 = max(0, y1 - 50)
            x2 = min(w, x2 + 50)
            y2 = min(h, y2 + 50)
            evidence_frame = frame[y1:y2, x1:x2]
        else:
            evidence_frame = frame
        
        cv2.imwrite(str(evidence_path), evidence_frame)
        return evidence_path
    
    def _record_violation(self, violation, frame_number, video_path=None):
        violation_data = {
            'violation_type': violation['type'],
            'timestamp': datetime.now(),
            'location': str(video_path) if video_path else None,
            'vehicle_type': violation.get('vehicle_type'),
            'license_plate': violation.get('license_plate'),
            'confidence': violation.get('confidence', 0.0),
            'speed': violation.get('speed'),
            'speed_limit': violation.get('speed_limit'),
            'evidence_image_path': violation.get('evidence_path'),
            'video_frame_number': frame_number,
            'metadata': {
                'bbox': violation.get('vehicle_bbox'),
                'plate_confidence': violation.get('plate_confidence', 0.0)
            }
        }
        violation_id = self.database.add_violation(violation_data)
        return violation_id
    
    def draw_all_detections(self, frame, results):
        annotated_frame = frame.copy()
        annotated_frame = self.vehicle_detector.draw_detections(
            annotated_frame, results['detections']['vehicles']
        )
        annotated_frame = self.traffic_light_detector.draw_traffic_lights(
            annotated_frame, results['detections']['traffic_lights']
        )
        for plate_info in results['detections']['plates']:
            annotated_frame = self.plate_recognizer.draw_plate(
                annotated_frame, plate_info
            )
        for violation in results['violations']:
            violation_type = violation['type']
            bbox = violation.get('vehicle_bbox')
            if bbox:
                x1, y1, x2, y2 = bbox
                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 0, 255), 4)
                label = f"VIOLATION: {violation_type}"
                if violation.get('license_plate'):
                    label += f" | Plate: {violation['license_plate']}"
                (text_width, text_height), _ = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
                )
                cv2.rectangle(annotated_frame, 
                            (x1, y1 - text_height - 10), 
                            (x1 + text_width, y1), (0, 0, 255), -1)
                cv2.putText(annotated_frame, label, (x1, y1 - 5),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        info_text = f"Frame: {results['frame_number']} | Violations: {len(results['violations'])}"
        cv2.putText(annotated_frame, info_text, (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        return annotated_frame
    
    def close(self):
        self.database.close()
