# tests/test_preprocess.py
import os
import csv
import pytest
import cv2
import numpy as np

# import your functions
from Pre_process import segment_disks, detect_marker_center

# Path to your test data:
CSV_PATH      = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/ground_truth.csv"))
IMAGE_FOLDER  = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/frames"))

@pytest.fixture(scope="session")
def ground_truth():
    """
    Load the CSV into a list of dicts, one per row:
      frame_id, disk_id, cx, cy, marker_x, marker_y
    """
    rows = []
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # convert numeric fields
            r["frame_id"]   = int(r["frame_id"])
            r["disk_id"]    = int(r["disk_id"])
            r["cx"]         = float(r["cx"])
            r["cy"]         = float(r["cy"])
            r["marker_x"]   = float(r["marker_x"])
            r["marker_y"]   = float(r["marker_y"])
            rows.append(r)
    return rows

@pytest.mark.parametrize("case", ground_truth())
def test_marker_detection(case):
    """
    For each CSV row:
      1) load the corresponding frame
      2) segment disks → find the disk matching cx,cy
      3) crop ROI & call detect_marker_center()
      4) assert the returned marker coords ≈ ground truth (within tol)
    """
    # 1) load frame
    frame_path = os.path.join(IMAGE_FOLDER, f"frame_{case['frame_id']:04d}.png")
    frame = cv2.imread(frame_path)
    assert frame is not None, f"Could not load {frame_path}"
    
    # 2) segment disks
    disks = segment_disks(frame)
    # disks: list of (cx, cy, radius)
    # find the disk whose center is closest to (case["cx"], case["cy"])
    dists = [np.hypot(cx - case["cx"], cy - case["cy"]) for cx, cy, _ in disks]
    best_idx = int(np.argmin(dists))
    cx, cy, r = disks[best_idx]
    assert dists[best_idx] < 5.0, f"Disk center mismatch: got {cx,cy}, expected {case['cx'],case['cy']}"
    
    # 3) crop ROI & call marker detection
    # you may have a helper already; otherwise:
    x0 = int(cx - r); y0 = int(cy - r)
    x1 = int(cx + r); y1 = int(cy + r)
    roi = frame[y0:y1, x0:x1]
    # Adjust ROI‑relative coords if detect_marker_center returns global coords
    mx, my = detect_marker_center(roi, (int(r), int(r)), r)
    
    # 4) compare to ground truth, allow a small tolerance
    tol = 5.0  # pixels
    # if mx,my are ROI‑relative, shift back:
    mx_global = mx + x0
    my_global = my + y0
    err = np.hypot(mx_global - case["marker_x"], my_global - case["marker_y"])
    assert err <= tol, (
        f"Marker detection error too large: {err:.1f}px "
        f"(got {mx_global:.1f},{my_global:.1f}, "
        f"expected {case['marker_x']:.1f},{case['marker_y']:.1f})"
    )
