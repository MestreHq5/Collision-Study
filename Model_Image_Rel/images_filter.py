import os
import shutil
from ultralytics import YOLO

# 1. Paths
MODEL_PATH = r"C:/Users/gonca/Desktop/Collisions DEM/Collision-Study/runs/pose/Puck_Runs/trial_01-3/weights/best.pt"
FRAMES_FOLDER = r"C:/Users/gonca/Pictures/Camera Roll/Novos Videos/extracted_frames"

# 2. Output folders
PUCKS_DIR = os.path.join(FRAMES_FOLDER, "has_pucks")
EMPTY_DIR = os.path.join(FRAMES_FOLDER, "empty_table")

os.makedirs(PUCKS_DIR, exist_ok=True)
os.makedirs(EMPTY_DIR, exist_ok=True)

# 3. Load model
model = YOLO(MODEL_PATH)

# Supported image formats
valid_extensions = (".jpg", ".jpeg", ".png")
image_files = [
    f
    for f in os.listdir(FRAMES_FOLDER)
    if f.lower().endswith(valid_extensions)
]

print(
    f"Found {len(image_files)} images to filter using model: {MODEL_PATH}\n"
)

puck_count = 0
empty_count = 0

for img_name in image_files:
    img_path = os.path.join(FRAMES_FOLDER, img_name)

    # Run inference with a low confidence threshold to capture faint/partial pucks
    results = model.predict(source=img_path, conf=0.25, verbose=False)

    # Check if any bounding boxes/detections were found
    if len(results[0].boxes) > 0:
        shutil.move(img_path, os.path.join(PUCKS_DIR, img_name))
        puck_count += 1
    else:
        shutil.move(img_path, os.path.join(EMPTY_DIR, img_name))
        empty_count += 1

print(f"🎉 Filtering complete!")
print(f"✅ Images with pucks: {puck_count} ➔ Saved to: {PUCKS_DIR}")
print(f"🗑️ Empty table images: {empty_count} ➔ Saved to: {EMPTY_DIR}")