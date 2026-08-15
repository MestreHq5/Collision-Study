# Detection
import cv2

# Process Modules
import numpy as np

# Built-in modules
import csv
import math
import sys
from pathlib import Path

# Personal Modules
import Pre_process as prp

# Third-party: YOLO Pose model for disk detection
from ultralytics import YOLO

# 1) Core global constants
FRAME_LIMIT_AVG  = 60 # maximum amount of frames needed to average the background
CLEAN_SECONDS = 2.0 # first part of the video where script averages the background
BLUR_KERNEL  = (5, 5) # diemnsion of the kernel used in the Gaussian Blur
DEFAULT_MASS = 0.0118 # default mass

# HSV ranges for the offset mark. Recalibrated this session from a broad survey
# (see CLAUDE.md) of 580 marker-blob samples pulled from 859 puck-containing
# frames spanning all 28 videos in Camera Roll/Novos Videos/ — a much broader
# base than earlier single-clip calibrations, which kept turning out to be
# overfit to whichever one clip they were validated against. Bounds are ~p1-p99
# of each color's measured (hue, sat, val) cluster, with the hue split placed
# in the natural gap between the two clusters (~80-89, only 6/580 samples).
GREEN_LOWER = np.array([48, 55, 25])
GREEN_UPPER = np.array([85, 245, 150])
BLUE_LOWER  = np.array([88, 55, 28])
BLUE_UPPER  = np.array([115, 175, 165])

# A real paint marker is a compact round dot; a false-positive blob from an
# over-permissive HSV floor (edge anti-aliasing, shadow, specular glint) tends
# to be a thin sliver following the disk's rim instead. Gate both area (scaled
# to the disk's own size, not a fixed tiny constant that any noise clears) and
# circularity so "no marker visible this frame" (legitimate — the marker
# rotates out of view) stays a null result instead of a wrong color lock.
# MARKER_MIN_AREA_FRAC came from the same broad survey: median real-marker
# area was ~4.4% of the disk's face, p25 ~2.5% — the previous 0.07 (7%) floor
# was above the median, silently rejecting most genuine detections.
MARKER_MIN_AREA_FRAC = 0.015   # min marker area as a fraction of the disk's face area
MARKER_MIN_CIRCULARITY = 0.62  # 4*pi*area/perimeter^2; validated true~0.72-0.83 vs false~0.61.
# Circularity carries most of the false-positive rejection burden (the known
# false case was 95px/circ~0.61 on a disk where even 0.07*area ~= 55px would
# NOT have rejected it on area alone) — area is a coarse floor, not the
# primary filter.
MARKER_MAX_CIRCULARITY = 0.90  # reject anything MORE circular than this too — a small
# (~28px) noise/compression-artifact blob measured 0.943, more "perfectly" round than any
# confirmed real marker (max observed 0.833). Surfaced once `detect_marker_center` started
# considering every valid contour instead of only the largest raw one (see Pre_process.py).

# Real disk diameter in mm (user-confirmed: 35mm radius, not 40mm — this drives
# scale_mm_per_px, so it was scaling every mm value in the CSV/Excel output ~14% high)
DISK_DIAMETER_MM = 70.0

# Marker search geometry: exclude only a small central disc (the offset
# marker, user-measured at 20-30mm from center on a 35mm-radius disk, is
# never near-center regardless of how wrong a given frame's bbox radius is)
# and otherwise search a generously padded crop with no outer distance bound
# — see resolve_marker_color's docstring for why a tight outer bound (either
# bbox-relative or mm-calibrated) was tried and measured to cost more recall
# than it was worth.
MARKER_DIST_MIN_FRAC = 0.3
MARKER_SEARCH_PAD_FACTOR = 3.5

# Stable color -> ID mapping (your requirement)
COLOR_ID_MAP = {"green": 0, "blue": 1}
ALL_IDS = sorted(COLOR_ID_MAP.values())  # [0,1]

# --- YOLO Pose detection settings ---
# Best fine-tuned run to date (see CLAUDE.md). Single class "puck", 2 keypoints
# per detection: kpt[0] = disk center, kpt[1] = offset color marker.
YOLO_WEIGHTS_REL = Path("runs") / "pose" / "train-5" / "weights" / "best.pt"
YOLO_CONF = 0.10          # directive: keep conf around 0.10-0.15; validated against real
                          # footage (240_25.mp4): 0.10 recovers frames 0.15 misses with zero
                          # measured false positives in puck-free stretches of the same video
YOLO_IOU = 0.5
YOLO_IMGSZ = 1280          # match training imgsz (train-5/args.yaml) for best accuracy
YOLO_MIN_RADIUS = 10
YOLO_MAX_RADIUS = 200
YOLO_DEDUP_DIST_PX = 30   # merge duplicate boxes closer than this (directive)
YOLO_KPT_CONF_MIN = 0.25  # minimum keypoint confidence to trust a keypoint
FALLBACK_GATE_PX = 200    # only look for a missing disk within this radius of its last seen position
FALLBACK_SEARCH_RADIUS_PX = 250  # how far from that last position a contour fallback candidate may be

_yolo_model = None
_yolo_device = None


def _resolve_model_path() -> Path:
    """PyInstaller-safe path to the model weights (mirrors helper.resource_path)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / YOLO_WEIGHTS_REL


def _get_yolo_model():
    """Lazily load (and cache) the YOLO Pose model + preferred device."""
    global _yolo_model, _yolo_device
    if _yolo_model is None:
        weights_path = _resolve_model_path()
        if not weights_path.exists():
            raise FileNotFoundError(f"YOLO pose weights not found at {weights_path}")
        _yolo_model = YOLO(str(weights_path))
        try:
            import torch
            _yolo_device = 0 if torch.cuda.is_available() else "cpu"
        except Exception:
            _yolo_device = "cpu"
    return _yolo_model, _yolo_device


def detect_disks_yolo(model, device, frame, conf=YOLO_CONF, iou=YOLO_IOU, imgsz=YOLO_IMGSZ,
                       min_radius=YOLO_MIN_RADIUS, max_radius=YOLO_MAX_RADIUS):
    """
    Runs the YOLO Pose model on a single frame and returns candidate disks:
      center:  (cx, cy) px  -> from the "center" keypoint if confident, else bbox center
      radius:  float px     -> from the bounding box
      marker_center: (mx, my) px or None -> raw "marker" keypoint (refined later via HSV)
      conf:    detection confidence (used for de-duplication)
    """
    results = model.predict(frame, conf=conf, iou=iou, imgsz=imgsz, device=device, verbose=False)[0]

    disks = []
    boxes = results.boxes
    if boxes is None or len(boxes) == 0:
        return disks

    xyxy = boxes.xyxy.cpu().numpy()
    confs = boxes.conf.cpu().numpy()

    kpts_xy = None
    kpts_conf = None
    if results.keypoints is not None:
        kpts_xy = results.keypoints.xy.cpu().numpy()
        if results.keypoints.conf is not None:
            kpts_conf = results.keypoints.conf.cpu().numpy()

    for i, box in enumerate(xyxy):
        x1, y1, x2, y2 = box
        r = ((x2 - x1) + (y2 - y1)) / 4.0
        if not (min_radius <= r <= max_radius):
            continue

        bbox_center = (float((x1 + x2) / 2.0), float((y1 + y2) / 2.0))
        center = bbox_center
        marker_center = None

        if kpts_xy is not None and kpts_xy.shape[1] >= 2:
            cx0, cy0 = kpts_xy[i, 0]
            c0_conf = float(kpts_conf[i, 0]) if kpts_conf is not None else 1.0
            if c0_conf >= YOLO_KPT_CONF_MIN and not (cx0 == 0 and cy0 == 0):
                center = (float(cx0), float(cy0))

            mx, my = kpts_xy[i, 1]
            m_conf = float(kpts_conf[i, 1]) if kpts_conf is not None else 1.0
            if m_conf >= YOLO_KPT_CONF_MIN and not (mx == 0 and my == 0):
                marker_center = (float(mx), float(my))

        disks.append({
            "center": center,
            "radius": float(r),
            "marker_center": marker_center,
            "conf": float(confs[i]),
            "source": "yolo",
        })

    return disks


def remove_duplicate_detections(disks, dist_threshold=YOLO_DEDUP_DIST_PX):
    """Keeps the highest-confidence detection among any cluster of near-duplicate boxes."""
    kept = []
    for d in sorted(disks, key=lambda d: -d.get("conf", 0.0)):
        too_close = any(
            math.hypot(d["center"][0] - k["center"][0], d["center"][1] - k["center"][1]) < dist_threshold
            for k in kept
        )
        if not too_close:
            kept.append(d)
    return kept


def fallback_contour_disks(frame, background, existing_disks, prev_pos, missing_ids,
                            dedup_dist=YOLO_DEDUP_DIST_PX, search_radius=FALLBACK_SEARCH_RADIUS_PX,
                            expected_radius=None):
    """
    Background-subtraction fallback for disks YOLO missed this frame. Only searches
    near each missing ID's last known position, rather than trusting every contour
    found on the table (directive: expected-region fallback, not whole-frame).
    """
    if not missing_ids:
        return []

    contour_disks = prp.segment_disks(
        frame, background,
        thresh_val=50, morph_kernel=(5, 5),
        min_radius=YOLO_MIN_RADIUS, max_radius=YOLO_MAX_RADIUS
    )

    # Sanity gate: a contour candidate is only a plausible puck if its radius is
    # close to a known puck radius. Without this, a glare/reflection blob (still
    # circular enough, still inside [YOLO_MIN_RADIUS, YOLO_MAX_RADIUS]) can slip
    # through, get a spurious HSV color match, and get locked in as a phantom
    # second puck by IDAssigner. Prefer this frame's own YOLO measurement; fall
    # back to the calibrated disk radius (from scale_mm_per_px) when YOLO found
    # nothing at all this frame; only use the generic wide bounds as a last resort.
    if existing_disks:
        ref_r = sum(ed["radius"] for ed in existing_disks) / len(existing_disks)
    elif expected_radius is not None:
        ref_r = expected_radius
    else:
        ref_r = None

    if ref_r is not None:
        r_lo, r_hi = ref_r * 0.5, ref_r * 1.8
    else:
        r_lo, r_hi = YOLO_MIN_RADIUS, YOLO_MAX_RADIUS

    # Drop contour candidates that just duplicate an already-found YOLO disk,
    # or whose size doesn't plausibly match a puck.
    candidates = [
        cd for cd in contour_disks
        if r_lo <= cd["radius"] <= r_hi
        and not any(
            math.hypot(cd["center"][0] - ed["center"][0], cd["center"][1] - ed["center"][1]) < dedup_dist
            for ed in existing_disks
        )
    ]

    added = []
    for pid in missing_ids:
        if pid not in prev_pos:
            continue
        px, py = prev_pos[pid]
        best_i, best_d = None, float("inf")
        for i, cd in enumerate(candidates):
            d = math.hypot(cd["center"][0] - px, cd["center"][1] - py)
            if d < best_d and d <= search_radius:
                best_d = d
                best_i = i
        if best_i is not None:
            cd = candidates.pop(best_i)
            added.append({
                "center": cd["center"],
                "radius": cd["radius"],
                "marker_center": None,
                "conf": 0.0,
                "source": "contour_fallback",
            })

    return added


def resolve_marker_color(frame, det):
    """
    Finds the HSV-confirmed marker centroid + color for a detection.

    Scans a generously padded crop around the disk (MARKER_SEARCH_PAD_FACTOR)
    for the largest matching color blob, excluding only a small central disc
    (MARKER_DIST_MIN_FRAC — the marker is never near-center). No outer
    distance bound and no keypoint-anchored fallback.

    An outer bound was tried two ways — tied to this frame's own bbox radius,
    and tied to scale_mm_per_px (the user-measured 20-30mm marker distance
    converted through a run-level calibration) — and both measured to cost
    more recall than they were worth: a per-frame bbox radius runs wildly
    inconsistent relative to the true visible disk (one case underestimated
    it by >3x, clipping real markers at the boundary — this is what was
    producing "detected position sits at the ROI border, not the true marker
    center"), and even the calibrated mm-based bound dropped whole-dataset
    recall from 42% to 28% on a validation sweep against 1004 disk detections
    across all 28 videos in Camera Roll/Novos Videos/ (some genuine markers'
    pixels legitimately extend well past the nominal disk radius on this
    footage). Precision against background instead comes from color range +
    MARKER_MIN_AREA_FRAC + MARKER_MIN_CIRCULARITY (a real paint marker is a
    compact round blob at a characteristic size; validated against known
    true/false cases — see CLAUDE.md) plus IDAssigner's position-lock, which
    already stops an occasional bad color read from corrupting an established
    track — full elimination of false positives isn't achievable through
    marker-search geometry/threshold tuning alone, so that's the containment
    layer, not this function.
    """
    cx, cy = det["center"]
    r = det["radius"]

    mask_inner = r * MARKER_DIST_MIN_FRAC
    mask_outer = r * MARKER_SEARCH_PAD_FACTOR
    pad_factor = MARKER_SEARCH_PAD_FACTOR

    min_area = MARKER_MIN_AREA_FRAC * math.pi * r * r

    mark = prp.detect_marker_center(frame, (cx, cy), r, GREEN_LOWER, GREEN_UPPER,
                                     pad_factor=pad_factor,
                                     min_area=min_area, min_circularity=MARKER_MIN_CIRCULARITY,
                                     max_circularity=MARKER_MAX_CIRCULARITY,
                                     mask_center=(cx, cy), mask_radius=mask_outer,
                                     mask_inner_radius=mask_inner)
    if mark is not None:
        return mark, "green"
    mark = prp.detect_marker_center(frame, (cx, cy), r, BLUE_LOWER, BLUE_UPPER,
                                     pad_factor=pad_factor,
                                     min_area=min_area, min_circularity=MARKER_MIN_CIRCULARITY,
                                     max_circularity=MARKER_MAX_CIRCULARITY,
                                     mask_center=(cx, cy), mask_radius=mask_outer,
                                     mask_inner_radius=mask_inner)
    if mark is not None:
        return mark, "blue"

    return None, None


class IDAssigner:
    """
    Assigns stable IDs (0/1) to detections:
      1) Position-lock: if a detection is within POSITION_LOCK_GATE_PX of an
         ID's last known position, that ID claims it immediately — before any
         color check. Position tracking is validated (this session, on real
         240fps footage) to be reliable frame-to-frame (median ~7px, p95
         ~46px of motion), while single-frame color detection is not: a
         one-off spurious HSV match on the WRONG disk can otherwise steal an
         already-tracked disk's identity via color-first assignment, causing
         the ID to flip-flop frame by frame. Position continuity is the more
         trustworthy signal once a track is established.
      2) Prefer color mapping (green->0, blue->1) for whatever's left — this
         is what actually establishes identity for a *new* track (no prior
         position to lock to), e.g. the first frame a disk enters frame, or
         after a long gap that moved it outside the lock gate.
      3) For detections with still-unknown color, assign by nearest neighbor
         to previous positions of the remaining IDs (unbounded — covers a
         disk reappearing after a multi-frame gap, farther than the lock gate
         but still the best match available).
      4) If no history exists, assign deterministically left->right.
    """

    POSITION_LOCK_GATE_PX = 60  # generous over the measured p95 (~46px) frame-to-frame motion

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

        # 1) Position-lock: tight-gate nearest-neighbor takes priority over color
        for pid in ALL_IDS:
            if pid not in self.prev_pos:
                continue
            best_i = None
            best_d = float("inf")
            for i, d in enumerate(detections):
                if i in used_idx:
                    continue
                dist = self._dist(self.prev_pos[pid], d["center"])
                if dist < best_d:
                    best_d = dist
                    best_i = i
            if best_i is not None and best_d <= self.POSITION_LOCK_GATE_PX:
                assigned[pid] = detections[best_i]
                used_idx.add(best_i)

        # 2) Color-first assignment for whatever's left
        for i, d in enumerate(detections):
            if i in used_idx:
                continue
            col = d.get("marker_color")
            if col and col.lower() in self.color_id_map:
                pid = self.color_id_map[col.lower()]
                # Avoid double-assigning the same ID (in case of false positive)
                if pid not in assigned:
                    assigned[pid] = d
                    used_idx.add(i)

        # 3) For remaining detections, use unbounded proximity to remaining IDs
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

        # 4) Deterministic fallback when no history (or still unmatched):
        # left-to-right order for detections, ascending ID order for remaining IDs
        if remaining_ids and remaining_dets:
            remaining_dets_sorted = sorted(remaining_dets, key=lambda t: t[1]["center"][0])  # by x
            remaining_ids_sorted = sorted(remaining_ids)
            for (ri, rd), pid in zip(remaining_dets_sorted, remaining_ids_sorted):
                assigned[pid] = rd

        # 5) Update history
        for pid, d in assigned.items():
            self.prev_pos[pid] = d["center"]

        # Return in a stable order [0,1] if present
        return [(pid, assigned[pid]) for pid in sorted(assigned.keys())]


def info(info_type, message):
    print(f"[{info_type}] {message}")


def main(video_path, bg_path, dtc_path, csv_path, fps_eff):

    # 1) Average background from a clean interval at the beggining of the filming
    # (still needed: sets the disk-size scale reference and backs the contour fallback)
    bg_path = prp.estimate_background_median(
        video_path         = video_path,
        clean_seconds      = CLEAN_SECONDS,
        frame_sample_limit = FRAME_LIMIT_AVG,
        blur_kernel        = BLUR_KERNEL,
        output_path        = bg_path,
        return_image       = False
    )
    background = cv2.imread(str(bg_path))

    if background is None:
        raise RuntimeError(f"Failed to load background at {bg_path}") # Error checking --> fatal program will end

    info("Done", "Background Averaged")

    # 1b) Load the YOLO Pose model once for the whole run
    yolo_model, yolo_device = _get_yolo_model()
    info("Info", f"YOLO Pose model loaded ({_resolve_model_path().name}) on device={yolo_device}")

    # 2) Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video {video_path}")  # Error checking --> fatal program will end

    # FIX: Read the exact frame rate directly from the recorded file container metadata
    file_fps = cap.get(cv2.CAP_PROP_FPS)
    if file_fps and file_fps > 1.0:
        fps = file_fps
    else:
        # Fallback to estimation only if file metadata tracking fails
        fps = min([30, 60], key=lambda x: abs(x - fps_eff))

    info("Info", f"File Container Native FPS: {fps:.2f}")
    dt  = 1.0 / fps if fps > 0 else 1/60  # Precise time elapsed per frame
    info("Info", f"Per frame time: {dt:.4f}s")

    # Variables, list of arrays for detections
    scale_mm_per_px = None
    # Collect several YOLO-sourced radii and take the median instead of locking
    # scale from a single first detection — measured on real footage that a
    # single frame's bbox radius can underestimate the true disk by >3x, which
    # would otherwise corrupt scale_mm_per_px (and therefore every mm value in
    # the output) for the entire run from one bad frame.
    RADIUS_SAMPLE_TARGET = 8
    radius_samples = []
    all_detections = []  # each entry: [frame, disk_id, cx_mm, cy_mm, mx_mm, my_mm, r_px]
    frame_idx = 0
    assigner = IDAssigner(COLOR_ID_MAP)

    # before the loop, open the writer
    w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    # Real camera FPS metadata (e.g. 240.10231632798067) has enough float precision
    # that mpeg4's timebase encoding overflows its max denominator (65535) and the
    # writer silently fails to produce a valid file. Round for the writer only —
    # `dt`/`fps` used for the physics stay full precision.
    out = cv2.VideoWriter(dtc_path, fourcc, round(fps, 2), (w, h))

    # 3) Main loop --> through each frame
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 4) Primary detection: YOLO Pose
        disks = detect_disks_yolo(yolo_model, yolo_device, frame)
        disks = remove_duplicate_detections(disks)

        # 4b) Hybrid fallback: if YOLO missed a disk, look for it via background
        # subtraction, but only in the region where it was last seen (not the
        # whole frame) so we don't reintroduce contour noise everywhere.
        if len(disks) < len(ALL_IDS) and assigner.prev_pos:
            covered_ids = set()
            for pid, prev in assigner.prev_pos.items():
                if any(IDAssigner._dist(prev, d["center"]) < FALLBACK_GATE_PX for d in disks):
                    covered_ids.add(pid)
            missing_ids = [pid for pid in ALL_IDS if pid not in covered_ids]
            expected_radius_px = (
                (DISK_DIAMETER_MM / 2.0) / scale_mm_per_px if scale_mm_per_px else None
            )
            disks.extend(fallback_contour_disks(
                frame, background, disks, assigner.prev_pos, missing_ids,
                expected_radius=expected_radius_px
            ))

        # 5) Compute scale from the median of several YOLO-sourced radii
        if scale_mm_per_px is None:
            for d in disks:
                if d.get("source") == "yolo" and d["radius"] > 0:
                    radius_samples.append(float(d["radius"]))
            if len(radius_samples) >= RADIUS_SAMPLE_TARGET:
                median_rpx = float(np.median(radius_samples))
                scale_mm_per_px = DISK_DIAMETER_MM / (2.0 * median_rpx)
                info("Info", f"Computed scale: {scale_mm_per_px:.3f} mm/px "
                              f"(median of {len(radius_samples)} radius samples)")

        # 6) Resolve marker color per disk (HSV, anchored on the YOLO keypoint when available)
        frame_dets = []
        for d in disks:
            cx_px, cy_px = d["center"]
            r_px = float(d["radius"])

            mark, marker_color = resolve_marker_color(frame, d)

            # 7) Drawing (disk & marker) on the original video
            # Green edge = YOLO detection, orange edge = contour fallback (debug aid)
            edge_color = (0, 255, 0) if d.get("source") == "yolo" else (0, 140, 255)
            cv2.circle(frame, (int(cx_px), int(cy_px)), int(r_px), edge_color, 2)
            cv2.circle(frame, (int(cx_px), int(cy_px)), 4, (0, 0, 255), -1)
            if mark is not None:
                mx_px, my_px = int(mark[0]), int(mark[1])
                cv2.circle(frame, (mx_px, my_px), 4, (0, 0, 255), -1)
            else:
                mx_px = my_px = None

            # 8 Append this disk detection
            frame_dets.append({
                "center": (float(cx_px), float(cy_px)),
                "radius": r_px,
                "marker_center": None if mark is None else (float(mark[0]), float(mark[1])),
                "marker_color": marker_color
            })

        # Assign stable IDs (0/1) for this frame
        assigned = assigner.assign(frame_dets)

        # 9) Save to CSV (mm units for centers & marker)
        for puck_id, det in assigned:
            cx_px, cy_px = det["center"]
            r_px = det["radius"]
            if scale_mm_per_px is None:
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
                r_px,
                det["marker_color"]
            ])

        # 10) Write the frame down
        out.write(frame)


        frame_idx += 1

    cap.release()
    out.release()

    # 7) Dump CSV
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "frame", "disk_id",
            "cx_mm", "cy_mm",
            "mx_mm", "my_mm",
            "r_px", "marker_color"
        ])
        writer.writerows(all_detections)

    info("Done", f"Saved {len(all_detections)} detections to disk_tracks.csv")
    return
