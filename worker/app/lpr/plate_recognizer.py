"""
License Plate Recognition Module
Detects and reads license plates from vehicles
"""

import cv2
import numpy as np
import easyocr
from pathlib import Path
import sys
import re

sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import LPR_CONFIDENCE_THRESHOLD


class LicensePlateRecognizer:
    def __init__(self, use_gpu=False):
        print("Initializing EasyOCR (this may take a moment)...")
        self.reader = easyocr.Reader(['en'], gpu=use_gpu)
        self.confidence_threshold = LPR_CONFIDENCE_THRESHOLD
        print("✓ License Plate Recognizer ready")
    
    def detect_and_read_plate(self, frame, vehicle_bbox=None):
        if vehicle_bbox is not None:
            x1, y1, x2, y2 = vehicle_bbox
            h, w = frame.shape[:2]
            x1 = max(0, x1 - 20)
            y1 = max(0, y1 - 20)
            x2 = min(w, x2 + 20)
            y2 = min(h, y2 + 20)
            search_region = frame[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1
        else:
            search_region = frame
            offset_x, offset_y = 0, 0

        preprocessed = self._preprocess_for_ocr(search_region)
        results = self.reader.readtext(preprocessed)

        plate_candidates = []
        for (bbox, text, confidence) in results:
            cleaned_text = self._clean_plate_text(text)
            if self._is_valid_plate(cleaned_text) and confidence > 0.35:
                adjusted_bbox = [
                    [int(bbox[0][0] + offset_x), int(bbox[0][1] + offset_y)],
                    [int(bbox[1][0] + offset_x), int(bbox[1][1] + offset_y)],
                    [int(bbox[2][0] + offset_x), int(bbox[2][1] + offset_y)],
                    [int(bbox[3][0] + offset_x), int(bbox[3][1] + offset_y)]
                ]
                plate_candidates.append({
                    'text': cleaned_text,
                    'bbox': adjusted_bbox,
                    'confidence': confidence
                })

        if plate_candidates:
            return max(plate_candidates, key=lambda x: x['confidence'])
        return None
    
    def _preprocess_for_ocr(self, image):
        h, w = image.shape[:2]
        if w < 120:
            scale = max(2, 120 // max(w, 1))
            image = cv2.resize(image, (w * scale, h * scale),
                               interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        gray  = clahe.apply(gray)
        filtered = cv2.bilateralFilter(gray, 9, 17, 17)
        thresh = cv2.adaptiveThreshold(
            filtered, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        return thresh
    
    def _clean_plate_text(self, text):
        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
        return cleaned
    
    def _is_valid_plate(self, text):
        if len(text) < 3 or len(text) > 10:
            return False
        return any(c.isalnum() for c in text)
    
    def draw_plate(self, frame, plate_info):
        if plate_info is None:
            return frame
        annotated_frame = frame.copy()
        bbox = plate_info['bbox']
        text = plate_info['text']
        confidence = plate_info['confidence']
        pts = np.array(bbox, np.int32)
        pts = pts.reshape((-1, 1, 2))
        cv2.polylines(annotated_frame, [pts], True, (0, 255, 0), 2)
        label = f"{text} ({confidence:.2f})"
        cv2.putText(annotated_frame, label, 
                   (bbox[0][0], bbox[0][1] - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        return annotated_frame
    
    def extract_plate_image(self, frame, plate_info):
        if plate_info is None:
            return None
        bbox = plate_info['bbox']
        x_coords = [pt[0] for pt in bbox]
        y_coords = [pt[1] for pt in bbox]
        x1, y1 = min(x_coords), min(y_coords)
        x2, y2 = max(x_coords), max(y_coords)
        plate_image = frame[y1:y2, x1:x2]
        return plate_image
