import cv2
import numpy as np
import csv
import Pre_process as prp

# 1) Core constants
VIDEO_PATH       = "Test Imaging/Video11.mp4"
BG_PATH          = "Test Imaging/table_background.png"
FRAME_LIMIT_AVG  = 50
CLEAN_SECONDS    = 2.0
BLUR_KERNEL      = (7, 7)

GREEN_LOWER = np.array([40, 80, 80])
GREEN_UPPER = np.array([90, 255, 255])
BLUE_LOWER  = np.array([100, 100, 100])
BLUE_UPPER  = np.array([130, 255, 255])

# real disk diameter in mm (adjust to your actual size)
DISK_DIAMETER_MM = 80.0 


def main(debug: bool = False):
    # 1) Estimate (or reload) background
    bg_path = prp.estimate_background_median(
        video_path         = VIDEO_PATH,
        clean_seconds      = CLEAN_SECONDS,
        frame_sample_limit = FRAME_LIMIT_AVG,
        blur_kernel        = BLUR_KERNEL,
        output_path        = BG_PATH,
        return_image       = False
    )
    background = cv2.imread(bg_path)
    if background is None:
        raise RuntimeError(f"Failed to load background at {bg_path}")

    # 2) Open video
    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        raise IOError(f"Cannot open video {VIDEO_PATH}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    dt  = 1.0 / fps if fps > 0 else 1/30

    scale_mm_per_px = None
    all_detections = []  # each entry: [frame, disk_id, cx_mm, cy_mm, mx_mm, my_mm, r_px]

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 3) Segment disks
        disks = prp.segment_disks(
            frame, background,
            thresh_val=50, use_otsu=False,
            morph_kernel=(5,5),
            min_radius=10, max_radius=200
        )

        # 4) Compute scale on first detection
        if scale_mm_per_px is None and disks:
            first_rpx = disks[0]["radius"]
            scale_mm_per_px = DISK_DIAMETER_MM / (2.0 * first_rpx)
            print(f"[Info] Computed scale: {scale_mm_per_px:.3f} mm/px")

        # 5) Process each disk
        for disk_id, d in enumerate(disks):
            cx_px, cy_px = d["center"]
            r_px         = d["radius"]

            # convert centroid to mm
            if scale_mm_per_px is None:
                continue
            cx_mm = cx_px * scale_mm_per_px
            cy_mm = cy_px * scale_mm_per_px
            
            cv2.circle(
            frame,
            (int(cx_px), int(cy_px)),
            int(r_px),
            (0, 255, 0),  # BGR green
            2             # line thickness
            )

            # draw disk’s centroid (red)
            cv2.circle(frame, (int(cx_px), int(cy_px)), 4, (0, 0, 255), -1)

            # detect colored mark (green then blue)
            mark = prp.detect_marker_center(
                frame, (cx_px, cy_px), r_px,
                GREEN_LOWER, GREEN_UPPER,
                debug=debug
            )
            if mark is None:
                mark = prp.detect_marker_center(
                    frame, (cx_px, cy_px), r_px,
                    BLUE_LOWER, BLUE_UPPER,
                    debug=debug
                )

            if mark:
                mx_px, my_px = mark
                # draw mark centroid (red)
                cv2.circle(frame, (mx_px, my_px), 4, (0, 0, 255), -1)
                mx_mm = mx_px * scale_mm_per_px
                my_mm = my_px * scale_mm_per_px
            else:
                mx_mm = my_mm = None

            # save detection
            all_detections.append([
                frame_idx, disk_id,
                cx_mm, cy_mm,
                mx_mm, my_mm,
                r_px
            ])

        # 6) Show and optionally quit
        cv2.imshow("Tracking", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        frame_idx += 1

    cap.release()
    cv2.destroyAllWindows()

    # 7) Dump CSV
    with open("disk_tracks.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "frame", "disk_id",
            "cx_mm", "cy_mm",
            "mx_mm", "my_mm",
            "r_px"
        ])
        writer.writerows(all_detections)

    print(f"[Done] Saved {len(all_detections)} detections to disk_tracks.csv")

if __name__ == "__main__":
    # set debug=True while tuning HSV/morphology, then False for batch runs
    main(debug=False)

