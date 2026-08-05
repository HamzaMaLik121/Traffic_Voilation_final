"""
License Plate Recognition Module (direct detector)
Detects license plates using custom AI and reads characters using EasyOCR
"""

import cv2
import numpy as np
from ultralytics import YOLO
import easyocr
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import LPR_MODEL, LPR_CONFIDENCE_THRESHOLD


class LPRDetector:
    def __init__(self, model_path=None):
        if model_path is None:
            model_path = LPR_MODEL
        
        try:
            self.model = YOLO(str(model_path))
            print(f"✓ Loaded LPR AI: {model_path}")
        except Exception as e:
            print(f"✗ Could not load LPR AI, using generic: {e}")
            self.model = YOLO('yolov8n.pt')
            
        print("📥 Initializing OCR Engine (This may take 1 min on first run)...")
        import torch
        use_gpu = torch.cuda.is_available()
        self.reader = easyocr.Reader(['en'], gpu=use_gpu)
        print(f"✓ OCR Engine Ready (Using {'GPU' if use_gpu else 'CPU'})")
        self.confidence_threshold = LPR_CONFIDENCE_THRESHOLD
        
    def detect_and_read(self, frame):
        results = self.model(frame, conf=self.confidence_threshold)
        
        detections = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                conf = float(box.conf[0])
                area = (x2 - x1) * (y2 - y1)
                detections.append({
                    'bbox': [x1, y1, x2, y2],
                    'conf': conf,
                    'area': area
                })
        
        detections = sorted(detections, key=lambda x: x['area'], reverse=True)[:2]
        
        lp_results = []
        for det in detections:
            x1, y1, x2, y2 = det['bbox']
            
            plate_crop = frame[y1:y2, x1:x2]
            if plate_crop.size == 0:
                continue
            
            text = self._read_text(plate_crop)
            
            lp_results.append({
                'bbox': [x1, y1, x2, y2],
                'text': text,
                'confidence': det['conf']
            })
        
        return lp_results
    
    def _read_text(self, plate_img):
        h, w = plate_img.shape[:2]
        if w < 120:
            scale = max(2, 120 // max(w, 1))
            plate_img = cv2.resize(plate_img, (w * scale, h * scale),
                                   interpolation=cv2.INTER_CUBIC)

        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        gray  = clahe.apply(gray)

        filtered = cv2.bilateralFilter(gray, 9, 17, 17)

        thresh = cv2.adaptiveThreshold(
            filtered, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        results = self.reader.readtext(
            thresh,
            allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'
        )

        full_text = "".join([res[1] for res in results])
        return full_text.upper().replace(" ", "")

    def draw_lpr(self, frame, lp_results):
        annotated_frame = frame.copy()
        for lp in lp_results:
            x1, y1, x2, y2 = lp['bbox']
            text = lp['text']
            
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (255, 255, 0), 2)
            cv2.rectangle(annotated_frame, (x1, y1 - 25), (x2, y1), (255, 255, 0), -1)
            cv2.putText(annotated_frame, text, (x1 + 5, y1 - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
                       
        return annotated_frame
