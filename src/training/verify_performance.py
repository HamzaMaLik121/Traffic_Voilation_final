"""
Performance Verification Tool
Reads training logs and prints the final 'Efficiency Rate' (Accuracy) for all models.
"""

import pandas as pd
from pathlib import Path
import sys

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import MODEL_DIR

def verify():
    print("\n" + "="*70)
    print("🚦 TRAFFIC VIOLATION SYSTEM - FINAL PERFORMANCE REPORT 🏆")
    print("="*70)
    print(f"{'DETECTED MODEL':<30} | {'PROGRESS':<12} | {'EFFICIENCY (mAP50)':<18}")
    print("-" * 70)

    models = ['traffic_light_detector', 'helmet_detector', 'lpr_detector', 'vehicle_detector']

    found_any = False
    for m in models:
        csv_path = MODEL_DIR / m / 'results.csv'

        if csv_path.exists():
            found_any = True
            try:
                df = pd.read_csv(csv_path)
                # Cleanup column names (YOLO often adds spaces)
                df.columns = [c.strip() for c in df.columns]

                # Get the best mAP50 (usually the last or best record)
                # columns: train/box_loss, ..., metrics/mAP50(B)
                map_col = [c for c in df.columns if 'mAP50(B)' in c]
                if map_col:
                    best_map = df[map_col[0]].max()
                    progress = f"{len(df)} Epochs"
                    print(f"{m:<30} | {progress:<12} | {best_map*100:>10.1f}% Accuracy")
                else:
                    print(f"{m:<30} | {'Incomplete':<12} | {'No metrics found':<18}")
            except Exception as e:
                print(f"{m:<30} | {'Error':<12} | {'Could not read log':<18}")
        else:
            print(f"{m:<30} | {'Missing':<12} | {'Weights not found':<18}")

    print("="*70)
    if not found_any:
        print("\n[WARN] No results found. Please ensure you have extracted 'all_trained_models.tar.gz'")
        print(f"   into your local directory: {MODEL_DIR}")
    else:
        print("\n[OK] REPORT COMPLETE. Open results.png in each folder for detailed graphs.")
    print("="*70 + "\n")

if __name__ == "__main__":
    verify()
