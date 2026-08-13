from ultralytics import YOLO

# Load your best trained model
model = YOLO("runs/pose/train-5/weights/best.pt")

# Run prediction on a video file
results = model.predict(
    source="C:/Users/gonca/Desktop/Collision_Study/NL_Slow/Recording.mp4",
    conf=0.25,        # Adjust threshold if needed (0.15 - 0.30 works well for pucks)
    save=True,        # Saves the annotated video
    show=False
)


print(results)