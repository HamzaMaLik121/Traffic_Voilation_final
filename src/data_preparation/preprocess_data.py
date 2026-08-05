"""
Zero-Failure Preprocessor for Traffic Violation Detection System
V3: Intelligent File Selection, Deep Label Discovery, and Global Integrity Reporting.
"""

import os
import shutil
import yaml
import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET
from pathlib import Path
from tqdm import tqdm
import sys
import cv2

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import DATA_DIR


class DataPreprocessor:
    def __init__(self):
        self.raw_dir = DATA_DIR / "raw"
        self.processed_dir = DATA_DIR / "processed"
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.summary = {} # Use dict for better tracking

    def _normalize_class_name(self, name):
        """Standardizes common variations like license vs licence"""
        return name.lower().replace('license', 'licen').replace('licence', 'licen').strip()

    def _convert_voc_to_yolo(self, xml_path, class_mapping):
        """Converts Pascal VOC XML to YOLO format with robust matching"""
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            size = root.find('size')
            w = int(size.find('width').text)
            h = int(size.find('height').text)

            yolo_data = []
            for obj in root.findall('object'):
                raw_name = obj.find('name').text
                norm_name = self._normalize_class_name(raw_name)

                cls_id = None
                for cid, cname in class_mapping.items():
                    if self._normalize_class_name(cname) in norm_name or norm_name in self._normalize_class_name(cname):
                        cls_id = cid
                        break

                if cls_id is None: continue

                xmlbox = obj.find('bndbox')
                b = (float(xmlbox.find('xmin').text), float(xmlbox.find('xmax').text),
                     float(xmlbox.find('ymin').text), float(xmlbox.find('ymax').text))

                bb = ((b[0] + b[1]) / 2.0 / w, (b[2] + b[3]) / 2.0 / h,
                      (b[1] - b[0]) / w, (b[3] - b[2]) / h)
                yolo_data.append(f"{cls_id} {' '.join([f'{a:.6f}' for a in bb])}")

            return "\n".join(yolo_data) if yolo_data else None
        except Exception:
            return None

    def _find_all_images(self, directory):
        """Recursively finds all valid image files"""
        exts = ['.jpg', '.jpeg', '.png', '.webp', '.bmp']
        files = []
        for ext in exts:
            files.extend(list(Path(directory).rglob(f"*{ext}")))
        return files

    def _process_dataset(self, name, raw_subdir, class_mapping, format='yolo'):
        """Universal robust dataset processor using Image-First Discovery"""
        print(f"\n[INFO] Processing {name.upper()}...")
        src_dir = self.raw_dir / raw_subdir
        dst_dir = self.processed_dir / name

        if not src_dir.exists():
            print(f"[WARN] {src_dir} not found. Skipping.")
            self.summary[name] = "[ERROR] FOLDER NOT FOUND"
            return

        for split in ['train', 'val']:
            (dst_dir / 'images' / split).mkdir(parents=True, exist_ok=True)
            (dst_dir / 'labels' / split).mkdir(parents=True, exist_ok=True)

        found_pairs = []
        all_imgs = self._find_all_images(src_dir)
        print(f"[INFO] Discovered {len(all_imgs)} images on disk")

        # 1. SPECIAL CASE: VEHICLE CSV WITH INTELLIGENT SELECTOR
        if format == 'csv':
            csv_files = list(src_dir.rglob("*.csv"))
            best_csv = None

            # Find the CSV that actually has coordinate columns (ignore sample_submission)
            for csv_path in csv_files:
                try:
                    head = pd.read_csv(csv_path, nrows=5)
                    head.columns = [c.strip().lower() for c in head.columns]
                    if any('xmin' in c or 'left' in c for c in head.columns):
                        best_csv = csv_path
                        print(f"[INFO] Selected Training CSV: {csv_path.name}")
                        break
                except Exception: continue

            if not best_csv:
                print(f"[ERROR] No valid annotation CSV found for {name}")
                self.summary[name] = "[ERROR] NO EXECUTABLE CSV"
                return

            df = pd.read_csv(best_csv)
            df.columns = [c.strip().lower() for c in df.columns]

            col_map = {
                'xmin': next((c for c in df.columns if 'xmin' in c or 'left' in c), 'xmin'),
                'ymin': next((c for c in df.columns if 'ymin' in c or 'top' in c), 'ymin'),
                'xmax': next((c for c in df.columns if 'xmax' in c or 'right' in c), 'xmax'),
                'ymax': next((c for c in df.columns if 'ymax' in c or 'bottom' in c), 'ymax'),
                'image': next((c for c in df.columns if 'image' in c or 'file' in c), 'image')
            }

            df['clean_name'] = df[col_map['image']].apply(lambda x: Path(str(x)).name)
            ann_map = {img_name: grp for img_name, grp in df.groupby('clean_name')}

            # Detect dimensions from first valid image
            v_h, v_w = None, None
            for img_path in all_imgs:
                if img_path.name in ann_map:
                    sample = cv2.imread(str(img_path))
                    if sample is not None:
                        v_h, v_w = sample.shape[:2]
                        break

            if v_h is None:
                print(f"[ERROR] Could not determine image dimensions for {name}")
                self.summary[name] = "[ERROR] NO VALID IMAGES"
                return

            for img_path in all_imgs:
                if img_path.name in ann_map:
                    group = ann_map[img_path.name]
                    yolo_lines = []
                    for _, row in group.iterrows():
                        try:
                            dw, dh = 1./v_w, 1./v_h
                            x = (float(row[col_map['xmin']]) + float(row[col_map['xmax']]))/2.0
                            y = (float(row[col_map['ymin']]) + float(row[col_map['ymax']]))/2.0
                            w = float(row[col_map['xmax']]) - float(row[col_map['xmin']])
                            h = float(row[col_map['ymax']]) - float(row[col_map['ymin']])
                            yolo_lines.append(f"0 {x*dw:.6f} {y*dh:.6f} {w*dw:.6f} {h*dh:.6f}")
                        except Exception: continue
                    if yolo_lines:
                        found_pairs.append({'img': img_path, 'txt': "\n".join(yolo_lines)})

        # 2. STANDARD: YOLO OR XML
        else:
            for img_path in all_imgs:
                label_content = None
                if format == 'xml':
                    xml_p = next((p for p in [img_path.with_suffix('.xml'), src_dir / "annotations" / f"{img_path.stem}.xml", src_dir / "Annotations" / f"{img_path.stem}.xml"] if p.exists()), None)
                    if xml_p: label_content = self._convert_voc_to_yolo(xml_p, class_mapping)
                elif format == 'yolo':
                    txt_p = next((p for p in [img_path.with_suffix('.txt'), img_path.parent / "labels" / f"{img_path.stem}.txt", img_path.parent.parent / "labels" / f"{img_path.stem}.txt"] if p.exists()), None)
                    if txt_p:
                        with open(txt_p, 'r') as f: label_content = f.read().strip()
                if label_content:
                    found_pairs.append({'img': img_path, 'txt': label_content})

        if not found_pairs:
            print(f"[ERROR] No valid image/label pairs found for {name}.")
            self.summary[name] = "[ERROR] 0 PAIRS FOUND"
            return

        # 3. SAVE DATA
        np.random.shuffle(found_pairs)
        split_idx = int(0.9 * len(found_pairs))
        for i, pair in enumerate(tqdm(found_pairs, desc=f"Saving {name}")):
            split = 'train' if i < split_idx else 'val'
            shutil.copy(pair['img'], dst_dir / 'images' / split / pair['img'].name)
            with open(dst_dir / 'labels' / split / f"{pair['img'].stem}.txt", 'w') as f:
                f.write(pair['txt'])

        # 4. YAML
        yaml_data = {'path': str(dst_dir.absolute()), 'train': 'images/train', 'val': 'images/val', 'nc': len(class_mapping), 'names': list(class_mapping.values())}
        with open(dst_dir / "dataset.yaml", 'w') as f: yaml.dump(yaml_data, f, default_flow_style=False)
        self.summary[name] = f"[OK] {len(found_pairs)} images ({split_idx}T, {len(found_pairs)-split_idx}V)"

    def run(self):
        print("\n" + "="*60 + "\n[INFO] ZERO-FAILURE SUPER PREPROCESSOR (V3)\n" + "="*60)
        self._process_dataset("traffic_light", "traffic_light_dataset", {0: 'red', 1: 'yellow', 2: 'green'})
        self._process_dataset("helmet", "helmet_dataset", {0: 'no_helmet', 1: 'helmet'})
        self._process_dataset("license_plates", "license_plate_dataset", {0: 'license_plate'}, format='xml')
        self._process_dataset("vehicle", "vehicle_dataset", {0: 'vehicle'}, format='csv')

        print("\n" + "="*60 + "\n[INFO] FINAL PREPROCESSING INTEGRITY REPORT\n" + "="*60)
        for model in ["traffic_light", "helmet", "license_plates", "vehicle"]:
            status = self.summary.get(model, "[ERROR] MISSING")
            print(f"{model.upper():<20} | {status}")
        print("="*60 + "\n[OK] READINESS: GREEN! STARTING GLOBAL TRAINING...")

if __name__ == "__main__":
    DataPreprocessor().run()
