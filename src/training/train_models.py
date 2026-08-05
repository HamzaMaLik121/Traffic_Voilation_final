"""
Model Training Script
Automates training for Helmet, LPR, Traffic Light, and Vehicle models.
Optimized for Kaggle P100 GPU.
"""

from ultralytics import YOLO
from pathlib import Path
import sys
import torch
import os

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import MODEL_DIR, DATA_DIR


class ModelTrainer:
    """Train custom detection models without user intervention"""

    def __init__(self):
        self.model_dir = MODEL_DIR
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir = DATA_DIR / "processed"

        # GPU Check
        self.device = 0 if torch.cuda.is_available() else 'cpu'
        print(f"\n[INFO] Using device: {'GPU (P100)' if self.device == 0 else 'CPU'}")

        # Dynamic settings
        self.batch_size = 32 if self.device == 0 else 8
        self.workers = 8 if self.device == 0 else 4

    def _train(self, model_name, dataset_subdir, epochs=100):
        """Internal generic trainer"""
        print("\n" + "="*60)
        print(f"[INFO] Training: {model_name.upper()}")
        print("="*60 + "\n")

        yaml_path = self.processed_dir / dataset_subdir / "dataset.yaml"
        if not yaml_path.exists():
            print(f"[WARN] Dataset not found: {yaml_path}. Skipping.")
            return

        model = YOLO('yolov8n.pt')

        results = model.train(
            data=str(yaml_path.absolute()),
            epochs=epochs,
            imgsz=640,
            batch=self.batch_size,
            name=model_name,
            patience=30, # Increased for better convergence
            save=True,
            device=self.device,
            workers=self.workers,
            project=str(self.model_dir),
            exist_ok=True,
            amp=True,
            cache=True,
            optimizer='AdamW'
        )

        print(f"[OK] Finished {model_name}. Weights saved to {self.model_dir}/{model_name}")
        return model

    def train_all(self, epochs=100):
        """Main entry point for Master Run"""
        print("\n" + "="*60)
        print("[INFO] STARTING MASTER TRAINING PIPELINE")
        print("="*60)

        # 1. Traffic Light
        self._train('traffic_light_detector', 'traffic_light', epochs=epochs)

        # 2. Helmet
        self._train('helmet_detector', 'helmet', epochs=epochs)

        # 3. License Plate
        self._train('lpr_detector', 'license_plates', epochs=epochs)

        # 4. Vehicle
        self._train('vehicle_detector', 'vehicle', epochs=epochs)

        print("\n" + "="*60)
        print("🏆 ALL MODELS TRAINED SUCCESSFULLY!")
        print("="*60)

    def export_all(self):
        """Exports all trained weights to ONNX for production"""
        print("\n📦 Exporting all models to ONNX...")
        for model_path in self.model_dir.rglob("best.pt"):
            print(f"  - Exporting {model_path.parent.parent.name}")
            model = YOLO(str(model_path))
            model.export(format='onnx')

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=str, choices=['helmet', 'lpr', 'traffic_light', 'vehicle', 'all'], default='all')
    parser.add_argument('--epochs', type=int, default=100)
    args = parser.parse_args()

    trainer = ModelTrainer()

    if args.model == 'all':
        trainer.train_all(epochs=args.epochs)
        trainer.export_all()
    elif args.model == 'helmet':
        trainer._train('helmet_detector', 'helmet', epochs=args.epochs)
    elif args.model == 'lpr':
        trainer._train('lpr_detector', 'license_plates', epochs=args.epochs)
    elif args.model == 'traffic_light':
        trainer._train('traffic_light_detector', 'traffic_light', epochs=args.epochs)
    elif args.model == 'vehicle':
        trainer._train('vehicle_detector', 'vehicle', epochs=args.epochs)
