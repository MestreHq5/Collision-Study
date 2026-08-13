from pathlib import Path
from ultralytics import YOLO

def main():
    # 1. Point to your updated dataset's data.yaml file
    # (Adjust "C:/Puck_Training/data.yaml" or "./Puck_Training/data.yaml" to your actual folder path)
    yaml_path = Path("C:/Users/gonca/Desktop/Collisions DEM/Collision-Study/Puck_Training/data.yaml").resolve()

    if not yaml_path.exists():
        print(f"[Error] Could not find data.yaml at {yaml_path}")
        print("Please check that your dataset folder contains data.yaml!")
        return

    print(f"[Info] Found dataset config at: {yaml_path}")

    # Load YOLOv8 Pose model pretrained weights
    model = YOLO("yolov8n-pose.pt")

    # Run training on your RTX 4060 GPU
    print("[Info] Starting training on RTX 4060...")
    results = model.train(
    data=str(yaml_path),
    epochs=45,             # Stop early (Epochs 30-40 were best)
    patience=10,           # Early stopping trigger if val loss stops improving
    weight_decay=0.01,    # Increased regularization to combat overfitting
    warmup_epochs=3.0,     # Stable learning rate warmup
    dropout=0.15, 
    batch=8,
    workers = 2,
    lr0=0.0005,
    imgsz = 1280, # Prevents classification head overfitting
    # Augmentations (adjust based on puck environment/lighting):
    hsv_h=0.015,
    hsv_s=0.7,
    hsv_v=0.4,
    degrees=15.0,          # Small rotations help with small round objects
    scale=0.5,
)

    print("\n[Success] Training complete!")
    print("Check 'Puck_Runs/240fps_trial_02' for performance graphs and trained weights!")

if __name__ == "__main__":
    main()