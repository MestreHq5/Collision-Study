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

# HSV ranges for the offset mark. Recalibrated this session against 240_25.mp4
# (see CLAUDE.md) — the previous GREEN_UPPER S/V ceiling (88, 129) was tuned for
# dimmer footage and rejected this clip's true marker pixels outright (measured
# median ~S214/V92, up to p99 ~S237/V139). Lower floors kept generous so dimmer/
# edge-blended instances (other lighting, other clips) still pass.
# BLUE_LOWER's floor is deliberately not as loose as GREEN's: on this footage,
# loosening it enough to catch the (glossy, highlight-heavy) blue marker's
# darker regions also let it catch thin rim/shadow slivers on the *green*
# puck's edge often enough to corrupt IDAssigner's color-first lock (a false
# color hit is worse than none — see MARKER_MIN_CIRCULARITY below, which
# catches most of what a looser floor would need to). Split the difference
# rather than reverting the floor all the way back to the pre-session values.
GREEN_LOWER = np.array([50, 30, 25])
GREEN_UPPER = np.array([70, 245, 150])
BLUE_LOWER  = np.array([100, 55, 45])
BLUE_UPPER  = np.array([120, 175, 165])

# A real paint marker is a compact round dot; a false-positive blob from an
# over-permissive HSV floor (edge anti-aliasing, shadow, specular glint) tends
# to be a thin sliver following the disk's rim instead. Gate both area (scaled
# to the disk's own size, not a fixed tiny constant that any noise clears) and
# circularity so "no marker visible this frame" (legitimate — the marker
# rotates out of view) stays a null result instead of a wrong color lock.
MARKER_MIN_AREA_FRAC = 0.07   # min marker area as a fraction of the disk's face area
MARKER_MIN_CIRCULARITY = 0.62  # 4*pi*area/perimeter^2; validated true~0.72-0.83 vs false~0.61.
# Circularity carries most of the false-positive rejection burden (the known
# false case was 95px/circ~0.61 on a disk where even 0.07*area ~= 55px would
# NOT have rejected it on area alone) — area is a coarse floor, not the
# primary filter. Lowered from 0.10 after a genuine, correctly-round (circ
# 0.83) marker on a smaller/dimmer clip measured at 28.5px against a 32.9px
# 0.10-derived requirement.
MARKER_MASK_PAD_MULT = 1.4    # padding on disk_radius for the "inside disk" mask (see resolve_marker_color)

# Real disk diameter in mm
DISK_DIAMETER_MM = 80.0

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

    Primary: scan the whole disk ROI (from the bbox-derived center/radius, not
    the keypoint) for the largest matching color blob. Measured on real footage
    this session, the YOLO "marker" keypoint lands on a non-marker specular
    highlight on the glossy disk body ~44% of the time (it moves with disk
    rotation just like the real marker does, so the model confuses the two) —
    whole-ROI search is immune to that since it doesn't depend on the keypoint's
    exact position, just on the true marker being the largest colored blob on
    the disk. The keypoint-anchored tight search is kept as a secondary
    fallback (e.g. useful mid-collision when two disks' ROIs risk overlapping).
    """
    cx, cy = det["center"]
    r = det["radius"]
    min_area = MARKER_MIN_AREA_FRAC * math.pi * r * r
    # The marker sits near the disk's edge by design (an *offset* mark) and
    # the bbox-derived radius runs a little tight — measured on real footage,
    # genuine marker pixels can sit past the raw disk radius (up to ~1.5x on
    # a small/dim marker). MARKER_MASK_PAD_MULT swept against both a known
    # true marker and a known false (background) case: 1.3-1.5x recovers the
    # true one, 1.8x+ starts letting the false one back in.
    mask_r = r * MARKER_MASK_PAD_MULT

    mark = prp.detect_marker_center(frame, (cx, cy), r, GREEN_LOWER, GREEN_UPPER,
                                     min_area=min_area, min_circularity=MARKER_MIN_CIRCULARITY,
                                     mask_center=(cx, cy), mask_radius=mask_r)
    if mark is not None:
        return mark, "green"
    mark = prp.detect_marker_center(frame, (cx, cy), r, BLUE_LOWER, BLUE_UPPER,
                                     min_area=min_area, min_circularity=MARKER_MIN_CIRCULARITY,
                                     mask_center=(cx, cy), mask_radius=mask_r)
    if mark is not None:
        return mark, "blue"

    marker_center = det.get("marker_center")
    if marker_center is not None:
        mx, my = marker_center
        kpt_radius = max(r * 0.35, 12)
        # Scale the area floor to *this* search region (kpt_radius), not the
        # full disk radius `r` used above. Reusing the disk-scaled min_area
        # here made the bar far too low relative to this much smaller crop —
        # measured letting a 414px^2 false blob through against a 55px^2 floor
        # meant for a ~15px-radius disk's full face.
        kpt_min_area = MARKER_MIN_AREA_FRAC * math.pi * kpt_radius * kpt_radius
        # mask_center/mask_radius keep the "must be inside the disk" check
        # anchored to the disk's real geometry (center/r), not the keypoint —
        # the keypoint is only used to bias where we crop. Without this, a
        # keypoint that's landed near/past the true edge (known to happen
        # ~44% of the time) lets the mask leak into background around the
        # disk entirely, matching whatever's out there instead of the puck.
        mark = prp.detect_marker_center(frame, (mx, my), kpt_radius, GREEN_LOWER, GREEN_UPPER,
                                         pad_factor=1.5, min_area=kpt_min_area, min_circularity=MARKER_MIN_CIRCULARITY,
                                         mask_center=(cx, cy), mask_radius=mask_r)
        if mark is not None:
            return mark, "green"
        mark = prp.detect_marker_center(frame, (mx, my), kpt_radius, BLUE_LOWER, BLUE_UPPER,
                                         pad_factor=1.5, min_area=kpt_min_area, min_circularity=MARKER_MIN_CIRCULARITY,
                                         mask_center=(cx, cy), mask_radius=mask_r)
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

        # 5) Compute scale on first detection (use first disk)
        if scale_mm_per_px is None and disks:
            first_rpx = float(disks[0]["radius"])
            if first_rpx > 0:
                scale_mm_per_px = DISK_DIAMETER_MM / (2.0 * first_rpx)
                info("Info", f"Computed scale: {scale_mm_per_px:.3f} mm/px")


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
