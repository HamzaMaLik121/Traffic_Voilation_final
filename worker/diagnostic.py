"""
Diagnostic test: run all models on a single frame to verify they load and detect.
"""
import cv2
import torch
from ultralytics import YOLO
from pathlib import Path
import os
import sys

ROOT = Path(__file__).parent
sys.path.append(str(ROOT))
from config.config import VEHICLE_MODEL, HELMET_MODEL, TRAFFIC_LIGHT_MODEL

def diagnostic_test(video_path):
    print(f"--- DIAGNOSTIC START: {video_path} ---")
    
    models = {
        "Base YOLO (yolov8n.pt)": YOLO('yolov8n.pt'),
        "Vehicle": YOLO(str(VEHICLE_MODEL)),
        "Helmet": YOLO(str(HELMET_MODEL)),
        "Traffic": YOLO(str(TRAFFIC_LIGHT_MODEL))
    }
    
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print("Error: Could not open video")
        return

    ret, frame = cap.read()
    if not ret:
        print("Error: Could not read first frame")
        return
        
    frame = cv2.resize(frame, (1280, 720))
    
    for name, model in models.items():
        print(f"\nTesting {name} Model...")
        print(f"Model Names: {model.names}")
        results = model(frame, conf=0.1)
        obj_count = 0
        for result in results:
            for box in result.boxes:
                obj_count += 1
                cls = int(box.cls[0])
                conf = float(box.conf[0])
                name_found = model.names[cls]
                print(f"  [{obj_count}] Found: {name_found} (Class {cls}) with conf: {conf:.3f}")
        print(f"  Total raw detections for {name}: {obj_count}")

    cap.release()
    print("\n--- DIAGNOSTIC COMPLETE ---")

if __name__ == "__main__":
    test_video = sys.argv[1] if len(sys.argv) > 1 else None
    if test_video and os.path.exists(test_video):
        diagnostic_test(test_video)
    else:
        print(f"Usage: python diagnostic.py <video_path>")
