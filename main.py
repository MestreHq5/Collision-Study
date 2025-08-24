# Detection 
import cv2

# Process Modules
import numpy as np

# Built-in modules
import csv
import math

# Personal Modules
import Pre_process as prp 

# 1) Core global constants
VIDEO_PATH       = "Test Imaging/Video11.mp4"
BG_PATH          = "Test Imaging/table_background.png"

FRAME_LIMIT_AVG  = 60 # maximum amount of frames needed to average the background 
CLEAN_SECONDS    = 2.0 # first part of the video where script averages the background
BLUR_KERNEL      = (5, 5) # diemnsion of the kernel used in the Gaussian Blur   

# HSV ranges for the offset mark
GREEN_LOWER = np.array([40, 80, 80])
GREEN_UPPER = np.array([90, 255, 255])
BLUE_LOWER  = np.array([100, 100, 100])
BLUE_UPPER  = np.array([130, 255, 255])

# Real disk diameter in mm 
DISK_DIAMETER_MM = 80.0

# Stable color -> ID mapping (your requirement)
COLOR_ID_MAP = {"green": 0, "blue": 1}
ALL_IDS = sorted(COLOR_ID_MAP.values())  # [0,1]


class IDAssigner:
    """
    Assigns stable IDs (0/1) to detections:
      1) Prefer color mapping (green->0, blue->1)
      2) For detections with unknown color, assign by nearest neighbor
         to previous positions of the remaining IDs.
      3) If no history exists, assign deterministically left->right.
    """
    def __init__(self, color_id_map):
        self.color_id_map = {k.lower(): v for k, v in color_id_map.items()}
        self.prev_pos = {}  # id -> (x, y)

    @staticmethod
    def _dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def assign(self, detections):
        """
        detections: list of dicts with keys:
          center: (cx, cy)
          radius: float
          marker_center: (mx, my) or None
          marker_color: "green"/"blue"/None
        returns: list of (assigned_id, detection_dict)
        """
        assigned = {}
        used_idx = set()

        # 1) Color-first assignment
        for i, d in enumerate(detections):
            col = d.get("marker_color")
            if col and col.lower() in self.color_id_map:
                pid = self.color_id_map[col.lower()]
                # Avoid double-assigning the same ID (in case of false positive)
                if pid not in assigned:
                    assigned[pid] = d
                    used_idx.add(i)

        # 2) For remaining detections, use proximity to remaining IDs
        remaining_ids = [pid for pid in ALL_IDS if pid not in assigned]
        remaining_dets = [(i, d) for i, d in enumerate(detections) if i not in used_idx]

        # If we have history, nearest-neighbor match
        for pid in list(remaining_ids):
            if pid in self.prev_pos:
                # pick closest remaining detection to this prev_pos
                best_i = None
                best_d = float("inf")
                for i, d in remaining_dets:
                    dist = self._dist(self.prev_pos[pid], d["center"])
                    if dist < best_d:
                        best_d = dist
                        best_i = i
                if best_i is not None:
                    # assign and remove from pools
                    for j, (ri, rd) in enumerate(remaining_dets):
                        if ri == best_i:
                            assigned[pid] = rd
                            remaining_dets.pop(j)
                            remaining_ids.remove(pid)
                            break

        # 3) Deterministic fallback when no history (or still unmatched):
        # left-to-right order for detections, ascending ID order for remaining IDs
        if remaining_ids and remaining_dets:
            remaining_dets_sorted = sorted(remaining_dets, key=lambda t: t[1]["center"][0])  # by x
            remaining_ids_sorted = sorted(remaining_ids)
            for (ri, rd), pid in zip(remaining_dets_sorted, remaining_ids_sorted):
                assigned[pid] = rd

        # 4) Update history
        for pid, d in assigned.items():
            self.prev_pos[pid] = d["center"]

        # Return in a stable order [0,1] if present
        return [(pid, assigned[pid]) for pid in sorted(assigned.keys())]


def main(debug: bool = False):
    
    # 1) Average background from a clean interval at the beggining of the filming
    bg_path = prp.estimate_background_median(
        video_path         = VIDEO_PATH,
        clean_seconds      = CLEAN_SECONDS,
        frame_sample_limit = FRAME_LIMIT_AVG,
        blur_kernel        = BLUR_KERNEL,
        output_path        = BG_PATH,
        return_image       = False
    )
    
    background = cv2.imread(bg_path)
    
    # Check if there was no error with the averaging 
    if background is None:
        raise RuntimeError(f"Failed to load background at {bg_path}")

    # 2) Open video
    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        raise IOError(f"Cannot open video {VIDEO_PATH}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    dt  = 1.0 / fps if fps > 0 else 1/30  # currently unused, but kept for future kinematics

    scale_mm_per_px = None
    all_detections = []  # each entry: [frame, disk_id, cx_mm, cy_mm, mx_mm, my_mm, r_px]

    frame_idx = 0
    assigner = IDAssigner(COLOR_ID_MAP)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 3) Segment disks
        disks = prp.segment_disks(
            frame, background,
            thresh_val=50,
            morph_kernel=(5,5),
            min_radius=10, max_radius=200
        )

        # 4) Compute scale on first detection (use first disk)
        if scale_mm_per_px is None and disks:
            first_rpx = float(disks[0]["radius"])
            if first_rpx > 0:
                scale_mm_per_px = DISK_DIAMETER_MM / (2.0 * first_rpx)
                print(f"[Info] Computed scale: {scale_mm_per_px:.3f} mm/px")

        # Build per-disk detections with marker color
        frame_dets = []
        for d in disks:
            cx_px, cy_px = d["center"]
            r_px         = float(d["radius"])

            # Try green
            mark = prp.detect_marker_center(
                frame, (cx_px, cy_px), r_px,
                GREEN_LOWER, GREEN_UPPER,
                debug=debug
            )
            marker_color = None
            if mark is not None:
                marker_color = "green"
            else:
                # Try blue
                mark = prp.detect_marker_center(
                    frame, (cx_px, cy_px), r_px,
                    BLUE_LOWER, BLUE_UPPER,
                    debug=debug
                )
                if mark is not None:
                    marker_color = "blue"

            # Drawing (disk & marker)
            cv2.circle(frame, (int(cx_px), int(cy_px)), int(r_px), (0, 255, 0), 2)
            cv2.circle(frame, (int(cx_px), int(cy_px)), 4, (0, 0, 255), -1)
            if mark is not None:
                mx_px, my_px = int(mark[0]), int(mark[1])
                cv2.circle(frame, (mx_px, my_px), 4, (0, 0, 255), -1)
            else:
                mx_px = my_px = None

            frame_dets.append({
                "center": (float(cx_px), float(cy_px)),
                "radius": r_px,
                "marker_center": None if mark is None else (float(mark[0]), float(mark[1])),
                "marker_color": marker_color
            })

        # Assign stable IDs (0/1) for this frame
        assigned = assigner.assign(frame_dets)

        # Save to CSV (mm units for centers & marker)
        for puck_id, det in assigned:
            cx_px, cy_px = det["center"]
            r_px = det["radius"]
            if scale_mm_per_px is None:
                # If scale is unknown (unlikely once we have a disk), skip writing this row
                continue
            cx_mm = cx_px * scale_mm_per_px
            cy_mm = cy_px * scale_mm_per_px

            if det["marker_center"] is not None:
                mx_px, my_px = det["marker_center"]
                mx_mm = mx_px * scale_mm_per_px
                my_mm = my_px * scale_mm_per_px
            else:
                mx_mm = my_mm = None

            all_detections.append([
                frame_idx, puck_id,
                cx_mm, cy_mm,
                mx_mm, my_mm,
                r_px
                # If you want the color in the CSV, also append: det["marker_color"]
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
            # If you added color above, add header: "marker_color"
        ])
        writer.writerows(all_detections)

    print(f"[Done] Saved {len(all_detections)} detections to disk_tracks.csv")


if __name__ == "__main__":
    # set debug=True while tuning HSV/morphology, then False for batch runs
    main(debug=False)
