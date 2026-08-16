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
import Post_process as pp

# Third-party
from ultralytics import YOLO  # YOLO Pose model for disk detection
import pandas as pd  # rotation-recovery pass reads/writes the detections CSV

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
DISK_RADIUS_MM = DISK_DIAMETER_MM / 2.0

# Marker search geometry: exclude only a small central disc (the offset
# marker, user-measured at 20-30mm from center on a 35mm-radius disk, is
# never near-center regardless of how wrong a given frame's bbox radius is).
# MARKER_SEARCH_PAD_FACTOR still sizes the *crop* generously (see
# resolve_marker_color) so a per-frame bbox-radius underestimate can't clip
# real signal out of the search region before the outer mask even runs, but
# the outer *mask* bound is now a hard physical one: the marker can never
# legitimately land outside the disk's own 35mm radius, so anything the
# color search finds past that is background/table, never the puck, by
# construction, not by threshold tuning. An earlier version of this file
# tried an outer bound (both bbox-relative and mm-calibrated) and reverted
# it for costing recall on a whole-dataset survey (42% -> 28%) — revisited
# after a controlled real-footage test (`240_15.mp4`, a motionless disk
# used as ground truth so any detected marker movement is pure noise, not
# real rotation) found detected positions landing up to 3.5x the disk
# radius away, i.e. confidently off the physical disk — the no-bound design
# was letting background noise dominate on this footage's dark disk
# material + overhead glare, not just occasionally missing a legitimately
# off-radius real marker. See CLAUDE.md for the full writeup.
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


def resolve_marker_color(frame, det, scale_mm_per_px=None):
    """
    Finds the HSV-confirmed marker centroid + color for a detection.

    Scans a generously padded crop around the disk (MARKER_SEARCH_PAD_FACTOR)
    for the largest matching color blob, excluding a small central disc
    (MARKER_DIST_MIN_FRAC — the marker is never near-center) and, when
    scale_mm_per_px is available, excluding anything past the disk's own
    physical 35mm radius (DISK_RADIUS_MM) too — see MARKER_SEARCH_PAD_FACTOR's
    comment for why this was reintroduced after being reverted once already.
    Deliberately keyed off the run-level scale calibration (a median over
    RADIUS_SAMPLE_TARGET frames), not this frame's own YOLO bbox radius `r`:
    `r` alone is exactly the noisy per-frame quantity that broke the first
    attempt at an outer bound (see Model section — it can underestimate the
    true disk by >3x), so bounding directly off it would still clip real
    markers on the frames where it's bad. `r` is only used as a crop-size
    floor now (never as the actual outer bound), so a bad `r` can make the
    crop bigger than necessary but can no longer make the mask wrong.
    No outer bound is applied for the handful of frames before
    scale_mm_per_px is calibrated (falls back to the old bbox-relative pad).

    Precision against background otherwise comes from color range +
    MARKER_MIN_AREA_FRAC + MARKER_MIN_CIRCULARITY (a real paint marker is a
    compact round blob at a characteristic size; validated against known
    true/false cases — see CLAUDE.md) plus IDAssigner's position-lock, which
    already stops an occasional bad color read from corrupting an established
    track.
    """
    cx, cy = det["center"]
    r = det["radius"]
    pad_factor = MARKER_SEARCH_PAD_FACTOR

    mask_inner = r * MARKER_DIST_MIN_FRAC
    if scale_mm_per_px:
        mask_outer = DISK_RADIUS_MM / scale_mm_per_px
    else:
        mask_outer = r * pad_factor

    # Crop must stay big enough to contain mask_outer even on a frame whose
    # bbox radius r underestimates the true disk -- pad off whichever of the
    # two implies the larger crop.
    crop_radius = max(r, mask_outer / pad_factor)

    min_area = MARKER_MIN_AREA_FRAC * math.pi * r * r

    mark = prp.detect_marker_center(frame, (cx, cy), crop_radius, GREEN_LOWER, GREEN_UPPER,
                                     pad_factor=pad_factor,
                                     min_area=min_area, min_circularity=MARKER_MIN_CIRCULARITY,
                                     max_circularity=MARKER_MAX_CIRCULARITY,
                                     mask_center=(cx, cy), mask_radius=mask_outer,
                                     mask_inner_radius=mask_inner)
    if mark is not None:
        return mark, "green"
    mark = prp.detect_marker_center(frame, (cx, cy), crop_radius, BLUE_LOWER, BLUE_UPPER,
                                     pad_factor=pad_factor,
                                     min_area=min_area, min_circularity=MARKER_MIN_CIRCULARITY,
                                     max_circularity=MARKER_MAX_CIRCULARITY,
                                     mask_center=(cx, cy), mask_radius=mask_outer,
                                     mask_inner_radius=mask_inner)
    if mark is not None:
        return mark, "blue"

    return None, None


# --- Flipped marker scheme: whole disk painted, marker = black dimple -------
# Not used by any footage yet (no repainted disks exist to test against) --
# see CLAUDE.md "Pre-repaint roadmap" for the objective this exists for:
# built now, against nothing but synthetic sanity checks, so that once real
# footage of the repainted disks exists the only remaining work is retuning
# the placeholder constants below against real samples, not writing new
# logic. Keep MARKER_SCHEME = "classic" until that footage exists and these
# constants have been retuned -- switching it blind would just swap one
# untested path for another on footage this scheme was never built for.
MARKER_SCHEME = "classic"  # "classic" (current footage) or "flipped" (repainted disks)

# Same green/blue family and hue windows as the current marker HSV as a
# starting point (paint spec calls for staying in that family, just more
# saturated/matte) -- the disk *body* covers a much larger, more uniform
# area than the small marker dot did, so these will very likely need
# *tightening* (narrower range) once real samples exist, not widening.
FLIPPED_GREEN_LOWER = GREEN_LOWER.copy()
FLIPPED_GREEN_UPPER = GREEN_UPPER.copy()
FLIPPED_BLUE_LOWER = BLUE_LOWER.copy()
FLIPPED_BLUE_UPPER = BLUE_UPPER.copy()
FLIPPED_MARKER_DARK_VALUE_FRAC = 0.55  # see detect_dark_marker_center; pure placeholder
# Dimple is roughly the same physical size/shape as the current marker dot,
# so its area/circularity gates start from the same calibrated constants --
# but MARKER_MIN_AREA_FRAC in particular was calibrated against a small
# blob on a large gray disk; against a large colored disk this fraction
# means a different absolute pixel count, so treat this as a placeholder
# too, not an inherited calibration.
FLIPPED_MARKER_MIN_AREA_FRAC = MARKER_MIN_AREA_FRAC
FLIPPED_MARKER_MIN_CIRCULARITY = MARKER_MIN_CIRCULARITY
FLIPPED_MARKER_MAX_CIRCULARITY = MARKER_MAX_CIRCULARITY


def resolve_marker_flipped_scheme(frame, det, scale_mm_per_px=None):
    """
    Flipped-scheme counterpart to resolve_marker_color: disk *identity*
    comes from the disk body's bulk color (classify_disk_bulk_color, a
    majority vote over the whole disk interior) instead of a small offset
    blob's hue, and the *marker* comes from the darkest compact region
    within that now-reliably-colored disk (detect_dark_marker_center)
    instead of a specific saturated hue. Same (marker_center, color) return
    shape as resolve_marker_color, so callers can swap between them via
    MARKER_SCHEME without any other change.
    """
    cx, cy = det["center"]
    r = det["radius"]

    color = prp.classify_disk_bulk_color(
        frame, (cx, cy), r,
        {"green": (FLIPPED_GREEN_LOWER, FLIPPED_GREEN_UPPER),
         "blue": (FLIPPED_BLUE_LOWER, FLIPPED_BLUE_UPPER)},
    )
    if color is None:
        return None, None

    pad_factor = MARKER_SEARCH_PAD_FACTOR
    if scale_mm_per_px:
        mask_outer = DISK_RADIUS_MM / scale_mm_per_px
    else:
        mask_outer = r * pad_factor
    crop_radius = max(r, mask_outer / pad_factor)
    min_area = FLIPPED_MARKER_MIN_AREA_FRAC * math.pi * r * r

    mark = prp.detect_dark_marker_center(
        frame, (cx, cy), crop_radius,
        pad_factor=pad_factor,
        min_area=min_area, min_circularity=FLIPPED_MARKER_MIN_CIRCULARITY,
        max_circularity=FLIPPED_MARKER_MAX_CIRCULARITY,
        mask_center=(cx, cy), mask_radius=mask_outer,
        mask_inner_radius=r * MARKER_DIST_MIN_FRAC,
        dark_value_frac=FLIPPED_MARKER_DARK_VALUE_FRAC,
    )
    return mark, color


def resolve_marker(frame, det, scale_mm_per_px=None):
    """Dispatches to the classic or flipped scheme per MARKER_SCHEME -- the single call site (main()) needing to change."""
    if MARKER_SCHEME == "flipped":
        return resolve_marker_flipped_scheme(frame, det, scale_mm_per_px)
    return resolve_marker_color(frame, det, scale_mm_per_px)


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
         to a *predicted* position for the remaining IDs — last known
         position extrapolated by that ID's last-seen velocity times how
         many frames it's been missing (gap) — gated at MAX_SPEED_PX_PER_FRAME
         * gap. Covers a disk reappearing after a multi-frame gap without
         handing the ID to an arbitrarily-far detection just because it's the
         closest one available: an unbounded version of this step used to do
         exactly that (see CLAUDE.md Known bugs), silently relocating a track
         onto an unrelated disk/background blob with no rejection at all, and
         that wrong position then became the new "last known position" for
         every future frame's lock/prediction until the real disk happened to
         wander back within range.
      4) If no history exists, assign deterministically left->right.
    """

    POSITION_LOCK_GATE_PX = 60  # generous over the measured p95 (~46px) frame-to-frame motion
    MAX_SPEED_PX_PER_FRAME = POSITION_LOCK_GATE_PX  # same bound, scaled by gap in step 3

    def __init__(self, color_id_map):
        self.color_id_map = {k.lower(): v for k, v in color_id_map.items()}
        self.prev_pos = {}      # id -> (x, y), most recent known position
        self.prev_prev_pos = {}  # id -> (x, y), second-most-recent (for velocity)
        # id -> frames pid was missing as of the end of the last completed
        # assign() call (0 if it was assigned that call). Frames elapsed for
        # the frame currently being resolved is always this + 1 -- see
        # _current_gap -- so both step 3 (mid-assign()) and predicted_pos
        # (which may be called externally, between assign() calls, e.g. by
        # the contour fallback for the *upcoming* frame) read the same
        # correct value without either one needing its own pre/post
        # increment bookkeeping.
        self.gap = {}

    @staticmethod
    def _dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _current_gap(self, pid):
        return self.gap.get(pid, 0) + 1

    def predicted_pos(self, pid):
        """
        Extrapolate pid's expected current position from its last known
        velocity (last two positions) times its current gap, or just its
        last position if no velocity estimate exists yet (only one sighting
        so far) or it's not being tracked at all. Exposed so callers (e.g.
        the contour fallback search) can search from where the disk is
        expected to be *now*, not where it was last actually seen.
        """
        if pid not in self.prev_pos:
            return None
        pos = self.prev_pos[pid]
        if pid not in self.prev_prev_pos:
            return pos
        gap = self._current_gap(pid)
        vx = pos[0] - self.prev_prev_pos[pid][0]
        vy = pos[1] - self.prev_prev_pos[pid][1]
        return (pos[0] + vx * gap, pos[1] + vy * gap)

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

        # 3) For remaining detections, velocity-gated nearest neighbor to
        # remaining IDs' predicted (not stale) positions
        remaining_ids = [pid for pid in ALL_IDS if pid not in assigned]
        remaining_dets = [(i, d) for i, d in enumerate(detections) if i not in used_idx]

        for pid in list(remaining_ids):
            if pid not in self.prev_pos:
                continue
            predicted = self.predicted_pos(pid)
            max_dist = self.MAX_SPEED_PX_PER_FRAME * self._current_gap(pid)
            best_i = None
            best_d = float("inf")
            for i, d in remaining_dets:
                dist = self._dist(predicted, d["center"])
                if dist < best_d:
                    best_d = dist
                    best_i = i
            if best_i is not None and best_d <= max_dist:
                for j, (ri, rd) in enumerate(remaining_dets):
                    if ri == best_i:
                        assigned[pid] = rd
                        remaining_dets.pop(j)
                        remaining_ids.remove(pid)
                        break

        # 4) Deterministic fallback, left-to-right order: only for IDs with
        # NO prior history at all (a genuinely new track, e.g. the first
        # frame a disk enters frame). IDs that DO have history but whose only
        # remaining candidate(s) failed step 3's distance gate must stay
        # unassigned here, not get force-matched anyway -- that would silence
        # the whole point of the gate (an implausibly-far detection would
        # still win by being the only one left).
        no_history_ids = [pid for pid in remaining_ids if pid not in self.prev_pos]
        if no_history_ids and remaining_dets:
            remaining_dets_sorted = sorted(remaining_dets, key=lambda t: t[1]["center"][0])  # by x
            remaining_ids_sorted = sorted(no_history_ids)
            for (ri, rd), pid in zip(remaining_dets_sorted, remaining_ids_sorted):
                assigned[pid] = rd

        # 5) Update history: reset gap to 0 for IDs seen this frame; for IDs
        # that stayed missing, store _current_gap(pid) (the value step 3 just
        # used to attempt resolving THIS frame) so the next call's
        # _current_gap continues counting from here, not from a stale value.
        for pid in ALL_IDS:
            if pid in assigned:
                if pid in self.prev_pos:
                    self.prev_prev_pos[pid] = self.prev_pos[pid]
                self.prev_pos[pid] = assigned[pid]["center"]
                self.gap[pid] = 0
            elif pid in self.prev_pos:
                self.gap[pid] = self._current_gap(pid)

        # Return in a stable order [0,1] if present
        return [(pid, assigned[pid]) for pid in sorted(assigned.keys())]


# --- Rotation recovery: physics-assisted recovery + interpolation fill ------
# (CLAUDE.md Rotation plan steps 3-5). Post-processing pass over an already-
# exported detections CSV -- separate from the live per-frame detection loop
# above, and never mutates it or the CSV it wrote. Scheme-agnostic: works the
# same regardless of MARKER_SCHEME, since it operates on whatever theta
# values fit_rotation_segments already extracted.
RECOVERY_SEARCH_RADIUS_FRAC = 0.35  # fraction of the estimated marker-offset
# radius used as the confirmation search's radius around the physics-
# predicted position -- generous enough to absorb some fit error, tight
# enough that it can't accidentally cover unrelated parts of the disk.
RECOVERY_MIN_CIRCULARITY = 0.5  # relaxed vs. MARKER_MIN_CIRCULARITY (0.62):
# a noise blob confidently mimicking a marker's shape AND landing within a
# few px of a physics-predicted position by chance is a much rarer
# coincidence than either alone, so the shape gate can afford to be looser
# here specifically.
MAX_FIT_RESIDUAL_STD_DEG = 45.0  # refuse to recover/interpolate against a
# segment fit whose own residual std exceeds this -- "0 outliers" alone
# does NOT mean a fit is precise enough to extrapolate from (see
# Post_process.fit_rotation_segments' omega_fit_residual_std_deg
# docstring): sigma-clipping only rejects points relative to the fit's own
# noise floor, so a fit built on mostly-poor data can inflate that floor
# and report zero outliers while still being nearly useless for
# extrapolation. Measured directly on real footage (240_25.mp4 disk 1): a
# segment reporting 0 outliers and a plausible-looking omega had a residual
# std of ~79 deg, and recovery against it produced errors averaging ~52 deg
# (several near-180, i.e. essentially random) on a held-out real-detection
# test. This threshold is a placeholder judgment call (not yet validated
# against a real fit that's genuinely precise enough to trust), not a
# calibrated cutoff -- but leaving the gate out entirely was measured to
# actively produce wrong, confident-looking output, which is worse than
# refusing to recover at all.


def _recover_segment_gaps(seg_df, cap, scale_mm_per_px, hsv_lower, hsv_upper,
                           recovery_search_radius_frac, recovery_min_circularity,
                           max_fit_residual_std_deg=MAX_FIT_RESIDUAL_STD_DEG):
    """
    Core of the recovery/interpolation fill for a single disk+segment's rows
    (one "before" or "after" slice of fit_rotation_segments' output). Mutates
    and returns seg_df's theta_unwrapped_deg/theta_source columns in place
    for every row that isn't already a trend-consistent "measured" inlier.
    No-op if the segment has no fit at all (fit_rotation_segments already
    leaves omega_fit_deg_per_frame/theta_fit_intercept_deg NaN in that case
    -- too few marker detections to satisfy its min_points floor).

    For each such row: predicts the marker's expected position from the
    segment's fitted trend (theta = omega_fit_deg_per_frame * frame +
    theta_fit_intercept_deg) and this disk's own measured marker-offset
    radius (median distance from center among that segment's inliers).
    Stage 1 (only if `cap` is given): seeks the real video to that frame and
    runs a real, narrow, high-sensitivity confirmation search centered on
    the predicted position, in this disk's already-known color (no
    green/blue ambiguity -- identity is already established by this point,
    unlike the live per-frame detector). This is safe to do narrowly,
    unlike a blind per-frame search over the whole disk, specifically
    because the search location is already physics-constrained (CLAUDE.md
    Rotation plan step 3). If found, re-anchors the result to the same 2*pi
    branch as the prediction so it stays continuous with the segment's
    trend, and tags theta_source "recovered". Stage 2 (always, as the
    fallback): if stage 1 wasn't run or didn't find anything, uses the pure
    predicted value with no further confirmation, tagged "interpolated".
    """
    inliers = seg_df[seg_df["theta_trend_consistent"] == True]
    fit_vals = seg_df["omega_fit_deg_per_frame"].dropna()
    intercept_vals = seg_df["theta_fit_intercept_deg"].dropna()
    residual_vals = seg_df["omega_fit_residual_std_deg"].dropna()
    if inliers.empty or fit_vals.empty or intercept_vals.empty:
        return seg_df
    if residual_vals.empty or float(residual_vals.iloc[0]) > max_fit_residual_std_deg:
        return seg_df  # fit isn't precise enough to extrapolate from -- see MAX_FIT_RESIDUAL_STD_DEG

    slope = float(fit_vals.iloc[0])
    intercept = float(intercept_vals.iloc[0])
    marker_radius_m = float(np.hypot(inliers["mx"] - inliers["cx"], inliers["my"] - inliers["cy"]).median())
    if not np.isfinite(marker_radius_m) or marker_radius_m <= 0:
        return seg_df  # can't build a search position without a radius estimate
    marker_radius_px = (marker_radius_m * 1000.0) / scale_mm_per_px if scale_mm_per_px else None

    needs_work = seg_df[seg_df["theta_trend_consistent"] != True]
    for idx, row in needs_work.iterrows():
        frame_idx = int(row["frame"])
        predicted_theta_deg = slope * frame_idx + intercept
        theta_rad = math.radians(predicted_theta_deg)

        found = None
        if cap is not None and marker_radius_px is not None:
            cx_px = row["cx"] * 1000.0 / scale_mm_per_px
            cy_px = row["cy"] * 1000.0 / scale_mm_per_px
            pred_mx_px = cx_px + marker_radius_px * math.cos(theta_rad)
            pred_my_px = cy_px + marker_radius_px * math.sin(theta_rad)

            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if ret:
                search_r = max(4.0, marker_radius_px * recovery_search_radius_frac)
                found = prp.detect_marker_center(
                    frame, (pred_mx_px, pred_my_px), search_r,
                    hsv_lower, hsv_upper, pad_factor=2.5,
                    min_area=MARKER_MIN_AREA_FRAC * math.pi * search_r * search_r,
                    min_circularity=recovery_min_circularity, max_circularity=1.0,
                    mask_center=(pred_mx_px, pred_my_px), mask_radius=search_r,
                )

        if found is not None:
            theta_actual = math.atan2(found[1] - cy_px, found[0] - cx_px)
            # Re-anchor to the SAME 2*pi branch as the prediction (not
            # necessarily the wrapped principal value) so this row's
            # theta_unwrapped_deg stays continuous with its segment's trend.
            k = round((theta_rad - theta_actual) / (2 * math.pi))
            seg_df.loc[idx, "theta_unwrapped_deg"] = math.degrees(theta_actual + 2 * math.pi * k)
            seg_df.loc[idx, "theta_source"] = "recovered"
        else:
            seg_df.loc[idx, "theta_unwrapped_deg"] = predicted_theta_deg
            seg_df.loc[idx, "theta_source"] = "interpolated"

    return seg_df


def fill_rotation_gaps(out_df, color, cap=None, scale_mm_per_px=None,
                        recovery_search_radius_frac=RECOVERY_SEARCH_RADIUS_FRAC,
                        recovery_min_circularity=RECOVERY_MIN_CIRCULARITY,
                        max_fit_residual_std_deg=MAX_FIT_RESIDUAL_STD_DEG):
    """
    Physics-assisted recovery + interpolation fill (CLAUDE.md Rotation plan
    steps 3-5), applied to one disk's Post_process.fit_rotation_segments
    output.

    Adds a theta_source column ("measured" / "recovered" / "interpolated" /
    None) and overwrites theta_unwrapped_deg for non-"measured" rows with a
    recovered or interpolated value; every other column (including the raw
    cx_mm/cy_mm/mx_mm/my_mm) is left exactly as fit_rotation_segments
    produced it. Frames in the "collision" segment, in a segment with no fit
    at all (too few marker detections for fit_rotation_segments' own
    min_points floor), or in a segment whose fit exists but isn't precise
    enough to trust (see max_fit_residual_std_deg), are left alone -- not
    recoverable by this mechanism.

    Args:
      out_df: one disk's fit_rotation_segments output.
      color: "green" or "blue" -- this disk's already-established identity
        (from COLOR_ID_MAP), used to search in the right HSV range with no
        ambiguity, unlike the live per-frame detector.
      cap: an open cv2.VideoCapture on the source video, for the stage-1
        recovery confirmation search. Pass None to skip straight to
        stage-2 interpolation-only -- e.g. when the video isn't available,
        or to measure "how much would pure interpolation alone get us"
        against a real-video-search comparison.
      scale_mm_per_px: required whenever cap is given (converts the fitted-
        trend prediction into a pixel search position).
      max_fit_residual_std_deg: refuse recovery/interpolation for a segment
        whose fit's own residual std exceeds this -- see
        MAX_FIT_RESIDUAL_STD_DEG for why "0 outliers" alone isn't enough to
        trust a fit for extrapolation, and the real-footage case that
        motivated adding this gate.
    """
    out = out_df.copy()
    out["theta_source"] = None
    out.loc[out["theta_trend_consistent"] == True, "theta_source"] = "measured"
    collision_mask = out["rotation_segment"] == "collision"
    out.loc[collision_mask & out["mx"].notna(), "theta_source"] = "measured"

    if cap is not None and not scale_mm_per_px:
        raise ValueError("scale_mm_per_px is required when cap is given (recovery needs pixel geometry).")

    hsv_lower, hsv_upper = (GREEN_LOWER, GREEN_UPPER) if color == "green" else (BLUE_LOWER, BLUE_UPPER)

    for label in ("before", "after"):
        seg_idx = out.index[out["rotation_segment"] == label]
        if len(seg_idx) == 0:
            continue
        filled_seg = _recover_segment_gaps(
            out.loc[seg_idx].copy(), cap, scale_mm_per_px, hsv_lower, hsv_upper,
            recovery_search_radius_frac, recovery_min_circularity, max_fit_residual_std_deg,
        )
        out.loc[seg_idx, ["theta_unwrapped_deg", "theta_source"]] = \
            filled_seg[["theta_unwrapped_deg", "theta_source"]]

    return out


def recover_and_fill_rotation(video_path, csv_path, out_csv_path=None, **fill_kwargs):
    """
    Two-disk CSV entry point for fill_rotation_gaps. Reads the exported
    detections CSV, fits+segments both disks sharing one collision frame
    (Post_process.fit_rotation), fills gaps via a real video search when
    possible, and writes a SEPARATE enriched CSV -- never overwrites the
    original -- with theta_source plus a filled theta_unwrapped_deg column.

    Returns (out_csv_path, combined_dataframe).
    """
    df = pd.read_csv(csv_path)
    id_color_map = {v: k for k, v in COLOR_ID_MAP.items()}
    df0_raw = df[df["disk_id"] == 0].copy()
    df1_raw = df[df["disk_id"] == 1].copy()
    if df0_raw.empty or df1_raw.empty:
        raise ValueError("recover_and_fill_rotation needs both disks present in the CSV "
                          "(the collision frame is computed from both).")

    out0, out1, summary = pp.fit_rotation(df0_raw, df1_raw)

    # Recomputed here rather than read from the CSV (not stored there) --
    # only used to size the video-frame search crop below, so an
    # independent re-derivation (same method main() uses) is fine; it
    # doesn't affect any reported mm value.
    all_r_px = pd.concat([df0_raw["r_px"], df1_raw["r_px"]])
    scale_mm_per_px = DISK_DIAMETER_MM / (2.0 * float(all_r_px.median()))

    cap = cv2.VideoCapture(video_path)
    filled0 = fill_rotation_gaps(out0, id_color_map[0], cap=cap, scale_mm_per_px=scale_mm_per_px, **fill_kwargs)
    filled1 = fill_rotation_gaps(out1, id_color_map[1], cap=cap, scale_mm_per_px=scale_mm_per_px, **fill_kwargs)
    cap.release()

    filled0["disk_id"] = 0
    filled1["disk_id"] = 1
    combined = pd.concat([filled0, filled1], ignore_index=True).sort_values(["frame", "disk_id"])

    out_path = out_csv_path or (str(Path(csv_path).with_suffix("")) + "_rotation_filled.csv")
    combined.to_csv(out_path, index=False)
    return out_path, combined


def info(info_type, message):
    print(f"[{info_type}] {message}")


def main(video_path, bg_path, dtc_path, csv_path, fps_eff, progress_callback=None):
    """
    progress_callback, if given, is called as progress_callback(frame_idx,
    total_frames) once per processed frame -- lets a caller (e.g. the GUI,
    from a background thread) show real progress instead of the window
    freezing silently for the whole run. Kept as a plain optional callback
    rather than importing any GUI framework here -- this module has no Qt
    dependency and shouldn't gain one just for this.
    """

    # 1) Load the YOLO Pose model first -- needed below to keep a puck that's
    # already on the table out of the background estimate (moved ahead of
    # background estimation for exactly that reason).
    yolo_model, yolo_device = _get_yolo_model()
    info("Info", f"YOLO Pose model loaded ({_resolve_model_path().name}) on device={yolo_device}")

    # 1b) Average background from a clean interval at the beggining of the filming
    # (still needed: sets the disk-size scale reference and backs the contour fallback).
    # puck_masker excludes any YOLO-detected disk region per sampled frame
    # from the median instead of assuming the whole window is puck-free --
    # a puck already resting on the table (or moving too little) for the
    # entire clean_seconds window would otherwise get baked into the
    # "background" as if it were table surface (see CLAUDE.md Known bugs;
    # estimate_background_median's own docstring has the full mechanism).
    def _puck_masker(frame):
        return [(d["center"][0], d["center"][1], d["radius"]) for d in detect_disks_yolo(yolo_model, yolo_device, frame)]

    bg_path = prp.estimate_background_median(
        video_path         = video_path,
        clean_seconds      = CLEAN_SECONDS,
        frame_sample_limit = FRAME_LIMIT_AVG,
        blur_kernel        = BLUR_KERNEL,
        output_path        = bg_path,
        return_image       = False,
        puck_masker        = _puck_masker,
    )
    background = cv2.imread(str(bg_path))

    if background is None:
        raise RuntimeError(f"Failed to load background at {bg_path}") # Error checking --> fatal program will end

    info("Done", "Background Averaged")

    # 2) Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video {video_path}")  # Error checking --> fatal program will end

    # Container's own frame count -- approximate for progress purposes only
    # (some containers misreport this slightly); never gates real processing,
    # which still runs until cap.read() returns False regardless.
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

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
            # Search from each missing ID's *predicted* position (velocity
            # extrapolated by however many frames it's been missing), not its
            # stale last-seen one -- matters most for exactly the case this
            # fallback exists for (a disk missing for several frames).
            predicted_pos = {
                pid: p for pid in missing_ids
                if (p := assigner.predicted_pos(pid)) is not None
            }
            disks.extend(fallback_contour_disks(
                frame, background, disks, predicted_pos, missing_ids,
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

            mark, marker_color = resolve_marker(frame, d, scale_mm_per_px)

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
        if progress_callback is not None:
            progress_callback(frame_idx, total_frames)

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
