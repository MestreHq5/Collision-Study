import os
import cv2


def extract_frames(source_folder, step=40):
    # 1. Define and create the output subfolder
    output_folder = os.path.join(source_folder, "extracted_frames")
    os.makedirs(output_folder, exist_ok=True)

    # Supported video formats
    video_extensions = (".mp4", ".mov", ".avi", ".mkv")

    # Get all video files in the source directory
    video_files = [
        f
        for f in os.listdir(source_folder)
        if f.lower().endswith(video_extensions)
    ]

    if not video_files:
        print(f"No video files found in '{source_folder}'.")
        return

    print(
        f"Found {len(video_files)} video(s). Extracting every {step}th frame...\n"
    )

    total_images_saved = 0

    # 2. Process each video
    for video_name in video_files:
        video_path = os.path.join(source_folder, video_name)
        base_name = os.path.splitext(video_name)[0]

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"⚠️ Could not open video: {video_name}")
            continue

        frame_count = 0
        saved_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break  # End of video stream

            # 3. Save every Nth frame (e.g., frame 0, 15, 30...)
            if frame_count % step == 0:
                # Construct unique file name: e.g., video1_frame_00015.jpg
                image_filename = f"{base_name}_frame_{frame_count:05d}.jpg"
                image_path = os.path.join(output_folder, image_filename)

                cv2.imwrite(image_path, frame)
                saved_count += 1
                total_images_saved += 1

            frame_count += 1

        cap.release()
        print(
            f"✅ {video_name}: Scanned {frame_count} frames ➔ Saved {saved_count} images."
        )

    print(
        f"\n🎉 Finished! Total {total_images_saved} images saved in:\n{output_folder}"
    )


# --- RUN SCRIPT ---
if __name__ == "__main__":
    # Replace with the path to your raw videos folder
    TARGET_FOLDER = r"C:/Users/gonca/Pictures/Camera Roll/Novos Videos"

    extract_frames(source_folder=TARGET_FOLDER, step=40)