"""
Quick test: verify multi-lane detection is working.
Run from project root: python test_lanes.py
"""
import sys, cv2, numpy as np
from pathlib import Path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app.detection.yolop_lane_detector import YolopLaneDetector

ld = YolopLaneDetector()

cap = cv2.VideoCapture(0)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
ret, frame = cap.read()
cap.release()

if not ret:
    print("[ERROR] Could not read video frame.")
    sys.exit(1)

frame = cv2.resize(frame, (1280, 720))
left, right = ld.detect_lanes(frame)

print(f'\nTotal lanes detected: {len(ld._all_lanes)}')
for i, lane in enumerate(ld._all_lanes):
    if lane:
        print(f'  Lane {i+1}: {len(lane)} points,  bottom-x={lane[0][0]}')

out = ld.draw_lanes(frame.copy())
cv2.imwrite('lane_test_result.png', out)
print('\nSaved: lane_test_result.png')
