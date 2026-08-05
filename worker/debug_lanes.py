"""
Diagnostic: visualize YOLOP's raw mask, morphology, and histogram peaks.
Run: python debug_lanes.py
"""
import sys, cv2, numpy as np
from pathlib import Path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from config.config import LANE_MODEL
import onnxruntime as ort

session = ort.InferenceSession(LANE_MODEL, providers=['CPUExecutionProvider'])
input_name = session.get_inputs()[0].name

cap = cv2.VideoCapture(0)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
ret, frame = cap.read(); cap.release()
if not ret:
    print("Failed to read frame")
    sys.exit(1)
frame = cv2.resize(frame, (1280, 720))
h, w = frame.shape[:2]

img = cv2.resize(frame, (640, 640))
img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
img -= [0.485, 0.456, 0.406]
img /= [0.229, 0.224, 0.225]
img = np.expand_dims(np.transpose(img, (2, 0, 1)), 0)

outputs = session.run(None, {input_name: img})
ll_seg = outputs[2]

lane_prob = ll_seg[0, 1]
print(f"Lane prob stats: min={lane_prob.min():.4f}  max={lane_prob.max():.4f}  mean={lane_prob.mean():.4f}")

mask_640 = (np.argmax(ll_seg[0], axis=0) == 1).astype(np.uint8)
print(f"Raw mask (640x640): {mask_640.sum()} lane pixels")

raw_vis = cv2.resize(mask_640 * 255, (w, h), interpolation=cv2.INTER_NEAREST)
cv2.imwrite('debug_1_raw_mask.png', raw_vis)

kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 15))
mask_morph = cv2.morphologyEx(mask_640, cv2.MORPH_CLOSE, kernel)
kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
mask_morph = cv2.erode(mask_morph, kernel2, iterations=1)

morph_vis = cv2.resize(mask_morph * 255, (w, h), interpolation=cv2.INTER_NEAREST)
cv2.imwrite('debug_2_morph_mask.png', morph_vis)

mask = cv2.resize(mask_morph, (w, h), interpolation=cv2.INTER_NEAREST)

roi_top = int(h * 0.40)
roi = mask[roi_top:, :]
hist = roi.sum(axis=0).astype(np.float32)
smooth_px = max(9, w // 90)
kernel_1d = np.ones(smooth_px) / smooth_px
hist = np.convolve(hist, kernel_1d, mode='same')

hist_img = np.zeros((300, w, 3), dtype=np.uint8)
hist_norm = (hist / hist.max() * 280).astype(int)
for x in range(w):
    cv2.line(hist_img, (x, 299), (x, 299 - hist_norm[x]), (0, 200, 255), 1)

print("Done. Open debug_*.png files to see results.")
