# Detection
import cv2

# Process Modules
import numpy as np

# Built-in modules
import csv
import math

# Personal Modules
import Pre_process as prp
import Post_process as pp

# 1) Core global constants
FRAME_LIMIT_AVG  = 60 # maximum amount of frames needed to average the background
CLEAN_SECONDS = 2.0 # first part of the video where script averages the background
BLUR_KERNEL  = (5, 5) # diemnsion of the kernel used in the Gaussian Blur
DEFAULT_MASS = 0.0118 # default mass

# Real disk diameter in mm (user-confirmed: 35mm radius, not 40mm — this drives
# scale_mm_per_px, so it was scaling every mm value in the CSV/Excel output ~14% high)
DISK_DIAMETER_MM = 70.0
DISK_RADIUS_MM = DISK_DIAMETER_MM / 2.0

# Marker search geometry: exclude only a small central disc (the offset
# marker, user-measured at 20-30mm from center on a 35mm-radius disk, is
# never near-center regardless of how wrong a given frame's detected radius
# is). MARKER_SEARCH_PAD_FACTOR still sizes the *crop* generously (see
# resolve_marker) so a per-frame radius underestimate can't clip real signal
# out of the search region before the outer mask even runs, but the outer
# *mask* bound is now a hard physical one: the marker can never legitimately
# land outside the disk's own 35mm radius, so anything the search finds past
# that is background/table, never the puck, by construction, not by
# threshold tuning. An earlier version of this file tried an outer bound and
# reverted it for costing recall on a whole-dataset survey (42% -> 28%) —
# revisited after a controlled real-footage test (a motionless disk used as
# ground truth so any detected marker movement is pure noise, not real
# rotation) found detected positions landing up to 3.5x the disk radius
# away, i.e. confidently off the physical disk. See CLAUDE.md for the full
# writeup.
MARKER_DIST_MIN_FRAC = 0.3
MARKER_SEARCH_PAD_FACTOR = 3.5

# Stable color -> ID mapping (your requirement)
COLOR_ID_MAP = {"green": 0, "blue": 1}
ALL_IDS = sorted(COLOR_ID_MAP.values())  # [0,1]

FALLBACK_MIN_RADIUS = 10
FALLBACK_MAX_RADIUS = 200
DEDUP_DIST_PX = 30        # merge duplicate detections closer than this
FALLBACK_GATE_PX = 200    # only look for a missing disk within this radius of its last seen position
FALLBACK_SEARCH_RADIUS_PX = 250  # how far from that last position a contour fallback candidate may be


def remove_duplicate_detections(disks, dist_threshold=DEDUP_DIST_PX):
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
                            dedup_dist=DEDUP_DIST_PX, search_radius=FALLBACK_SEARCH_RADIUS_PX,
                            expected_radius=None):
    """
    Background-subtraction fallback for disks the color detector missed this
    frame. Only searches near each missing ID's last known position, rather
    than trusting every contour found on the table (expected-region fallback,
    not whole-frame).
    """
    if not missing_ids:
        return []

    contour_disks = prp.segment_disks(
        frame, background,
        thresh_val=50, morph_kernel=(5, 5),
        min_radius=FALLBACK_MIN_RADIUS, max_radius=FALLBACK_MAX_RADIUS
    )

    # Sanity gate: a contour candidate is only a plausible puck if its radius is
    # close to a known puck radius. Without this, a glare/reflection blob (still
    # circular enough, still inside [FALLBACK_MIN_RADIUS, FALLBACK_MAX_RADIUS])
    # can slip through, get a spurious HSV color match, and get locked in as a
    # phantom second puck by IDAssigner. Prefer this frame's own color-detected
    # radius; fall back to the calibrated disk radius (from scale_mm_per_px)
    # when nothing was found at all this frame; only use the generic wide
    # bounds as a last resort.
    if existing_disks:
        ref_r = sum(ed["radius"] for ed in existing_disks) / len(existing_disks)
    elif expected_radius is not None:
        ref_r = expected_radius
    else:
        ref_r = None

    if ref_r is not None:
        r_lo, r_hi = ref_r * 0.5, ref_r * 1.8
    else:
        r_lo, r_hi = FALLBACK_MIN_RADIUS, FALLBACK_MAX_RADIUS

    # Drop contour candidates that just duplicate an already-found disk,
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


# --- Marker detection: whole disk painted, marker = black/grey dimple ------
# Disks are painted a large, saturated, matte color (whole body, not just a
# small offset dot) with the offset marker itself a black-painted dimple --
# see CLAUDE.md "Marker detection" for the paint spec and the real-footage
# survey that calibrated the constants below (95 green-disk / 251 blue-disk
# body samples, ~94/250 dimple samples; p1/p50/p99 percentiles).
#
# Real body-color survey found blue paint saturation runs much hotter than
# first assumed (observed S up to ~248) while green's range was already
# comfortably inside the initial bounds -- tightened both here now that real
# data exists.
GREEN_LOWER = np.array([60, 55, 30])
GREEN_UPPER = np.array([85, 110, 110])
BLUE_LOWER = np.array([95, 100, 70])
BLUE_UPPER = np.array([112, 255, 190])
MARKER_DARK_VALUE_FRAC = 0.55  # measured real dimple-V/body-V ratio: p50 ~0.37-0.46,
# p99 ~0.61-0.63 -- the inherited placeholder already sits above nearly all real
# ratios (safe), so left as-is; only the ~1% tail past 0.55 would be missed.
# That p50-p99 survey was blue-disk-dominated (95 green / 251 blue body samples,
# see CLAUDE.md) and this single global constant hid a real per-color split: the
# black dimple's own absolute brightness is roughly constant regardless of which
# disk it's painted on, but this scheme thresholds RELATIVE to that disk's own
# median V, and green's paint measures far darker overall than blue's (GREEN_
# UPPER's V cap is 110 vs BLUE_UPPER's 190, confirmed again in a 2026-09-18
# measurement on clips 3/5: green body median V ~79-85, dimple V ~50-60 ->
# ratio ~0.6-0.65, ABOVE 0.55). Net effect measured end-to-end on clips 3 & 5
# (detector.main(), real pipeline): green marker found in 0/40 rows at 0.55 vs
# blue's 78-83% -- not a shape/area gate problem, the dark-pixel mask was
# simply empty for green before cleanup even ran. A frac sweep on the same two
# clips (both-clips-combined green recall) found 0.55:14%, 0.65:50%, 0.70:93%,
# 0.72:100%, with the 0.72 hits visually confirmed landing on the real dimple
# (not shadow/noise) across sampled frames -- see MARKER_DARK_VALUE_FRAC_GREEN
# below. This is a software mitigation, not the real fix -- the real fix is a
# brighter/lighter green paint (raising the disk body's own V) so green gets
# the same contrast margin blue already has; revisit this constant (and
# consider reverting to one shared value) once that repaint happens.
MARKER_DARK_VALUE_FRAC_GREEN = 0.72
MARKER_MIN_AREA_FRAC = 0.012  # measured real dimple area_frac p1 ~0.016-0.019;
# floor nudged slightly below that for margin
MARKER_MIN_CIRCULARITY = 0.62  # measured real p1 ~0.70-0.73, comfortably above this floor
MARKER_MAX_CIRCULARITY = 0.94  # measured real p99 ~0.91-0.92 -- a 0.90 ceiling
# would have rejected ~1% of real dimples for being "too circular"; raised for margin

# 2026-09-19: real 18-clip batch (`Camera Roll/New Disks/`) diagnosis found the
# per-frame dimple recall (given the disk itself was found) is already high on
# most clips (80-100%) with the constants above -- the batch's low overall
# theta coverage traces mostly to two real, physical causes, not a threshold
# bug: (a) motion blur during the fast approach/separation around contact
# smearing the small dimple below any reasonable contrast threshold (visually
# confirmed on 4.mp4 blue, frames ~123-131), and (b) the marker rotating to a
# camera-facing arc where it's genuinely foreshortened/self-occluded by the
# disk's own rim from this side-mounted camera position (visually confirmed on
# 17.mp4 green: no visible dark dimple at all for ~15 consecutive frames, then
# a real one at frame 214) -- later confirmed (user, 2026-09-19) that clips
# 17/18 were shot with a previous, grey-bodied (not black) dimple, i.e. lower
# marker/body contrast by construction, not a detection bug. Neither cause is
# fixable by retuning a threshold -- see Post_process's per-segment theta
# interpolation for the actual fix (theta vs. frame is linear between
# collisions on this frictionless table regardless, so filling those gaps by
# interpolating the segment's own measured neighbors is physically correct,
# not just a stopgap).
# What IS a real, measured threshold gap: a handful of frames sit right at the
# edge of MARKER_DARK_VALUE_FRAC(_GREEN) with a genuinely darker-than-
# background but marginally-subtle dimple (measured on 17.mp4 green frame 213,
# one frame before the strict pass already succeeds at 214). MARKER_
# RELAX_FRAC_DELTA gives detect_dark_marker_center one relaxed retry for
# exactly these marginal misses, gated by MARKER_MAX_AREA_FRAC so the
# relaxed pass can't mistake a frame where the WHOLE disk dipped darker
# (motion blur / passing shadow / exposure) for the marker -- measured on the
# same clip (frames ~205-212) that relaxing the threshold without a size cap
# would otherwise catch a >1000px near-disk-sized blob, not the ~100-300px the
# real dimple actually measures.
# Net effect on the same 10-clip subset (the rest of `New Disks/` wasn't yet
# in the repo as of this session -- see CLAUDE.md): blue recall on 3 clips
# jumped 52-77% -> 95-100% (previously-missed marginal frames, confirmed
# visually landing on the real dimple through motion blur), green stayed
# ~85-100% (already fine), and 17/18.mp4's real occlusion-limited stretches
# picked up one or two more genuine reads each without any new false
# positives on the frames the max_area gate exists to reject -- no clip
# regressed.
MARKER_RELAX_FRAC_DELTA = 0.10
MARKER_MAX_AREA_FRAC = 0.12  # generous margin above MARKER_MIN_AREA_FRAC's
# measured real dimple floor (~0.012-0.019) -- no real per-clip max-area survey run yet
# (only the min side was surveyed, see MARKER_MIN_AREA_FRAC), but a near-disk-sized
# false blob measures far larger than this regardless (the 17.mp4 case above filled most of
# the disk's own face), so this placeholder already does its job of rejecting that case;
# revisit with a real survey if the relaxed retry ever needs finer tuning

# Identify-by-exclusion net (2026-09-17, user-observed): under direct overhead
# glare the green paint specifically reads as desaturated grey rather than
# green, dropping below GREEN_LOWER's saturation floor -- but since
# exactly two disks/colors exist in this study (COLOR_ID_MAP), whichever one
# ISN'T the confidently-found color is unambiguous. This range is
# deliberately much looser on saturation than either real color's calibrated
# window (catches a washed-out disk), but only ever used to relax the COLOR
# gate -- the shape gates (radius/circularity) stay at full strictness, and
# it's only ever tried when the strict search found exactly one of the two
# disks (see detect_disks_color) -- never both, never neither, so it can't
# manufacture a second disk out of noise when only one is genuinely on table.
EXCLUSION_LOWER = np.array([45, 20, 30])
EXCLUSION_UPPER = np.array([135, 255, 255])


def resolve_marker(frame, det, scale_mm_per_px=None):
    """
    Resolves a detection's disk *identity* and offset *marker* position.
    Identity comes from the disk body's bulk color (classify_disk_bulk_color,
    a majority vote over the whole disk interior) instead of a small offset
    blob's hue, and the marker comes from the darkest compact region within
    that now-reliably-colored disk (detect_dark_marker_center) instead of a
    specific saturated hue -- the disk body itself is the color signal now,
    so the marker's only distinguishing feature left is that it's dark.
    Returns (marker_center_xy_or_None, color_or_None).
    """
    cx, cy = det["center"]
    r = det["radius"]

    # If the position detector already determined this disk's identity via
    # its own HSV search (detect_disks_color knows which mask it matched,
    # including an identify-by-exclusion call), reuse it instead of
    # re-running an independent bulk-color vote -- two separate color checks
    # disagreeing with each other is exactly the kind of instability that
    # could destabilize IDAssigner's color-first fallback for new tracks
    # (user-requested continuity check, 2026-09-17). Detections without a
    # known color yet (e.g. the contour_fallback path) fall through to the
    # original bulk-vote lookup.
    color = det.get("color")
    if color is None:
        color = prp.classify_disk_bulk_color(
            frame, (cx, cy), r,
            {"green": (GREEN_LOWER, GREEN_UPPER),
             "blue": (BLUE_LOWER, BLUE_UPPER)},
        )
    if color is None:
        return None, None

    pad_factor = MARKER_SEARCH_PAD_FACTOR
    if scale_mm_per_px:
        mask_outer = DISK_RADIUS_MM / scale_mm_per_px
    else:
        mask_outer = r * pad_factor
    crop_radius = max(r, mask_outer / pad_factor)
    min_area = MARKER_MIN_AREA_FRAC * math.pi * r * r
    max_area = MARKER_MAX_AREA_FRAC * math.pi * r * r

    mark = prp.detect_dark_marker_center(
        frame, (cx, cy), crop_radius,
        pad_factor=pad_factor,
        min_area=min_area, min_circularity=MARKER_MIN_CIRCULARITY,
        max_circularity=MARKER_MAX_CIRCULARITY,
        mask_center=(cx, cy), mask_radius=mask_outer,
        mask_inner_radius=r * MARKER_DIST_MIN_FRAC,
        # Green's disk body reads measurably darker than blue's (see
        # MARKER_DARK_VALUE_FRAC's comment) -- the same relative
        # threshold that reliably isolates blue's dimple leaves near-zero
        # margin for green's, so green gets its own retuned constant.
        dark_value_frac=(MARKER_DARK_VALUE_FRAC_GREEN if color == "green"
                          else MARKER_DARK_VALUE_FRAC),
        max_area=max_area,
        relax_frac_delta=MARKER_RELAX_FRAC_DELTA,
    )
    return mark, color


# --- Disk position via HSV color contour ------------------------------------
# Only viable because the disk *body* itself is a large, saturated, matte
# color to threshold on; would not have worked against the old gray-body
# disks (see prp.segment_disks_by_color docstring).
COLOR_DISK_MIN_RADIUS = 30   # px; placeholder for this webcam's 1080p framing --
COLOR_DISK_MAX_RADIUS = 120  # measured real disk radius on the first 3 test clips
                             # was ~40-66px (median ~48-57px); retune if camera
                             # distance/framing changes.
COLOR_DISK_MIN_CIRCULARITY = 0.75


def detect_disks_color(frame, color_ranges=None):
    """
    Primary position detector: finds at most one disk per color (the largest
    contour passing the gates, mirroring remove_duplicate_detections' "keep
    the best" logic instead of needing it). Returns a list of dicts with
    "center", "radius", "marker_center" (always None here -- filled in later
    by resolve_marker), "conf", "source", "color". "conf" is a coarse
    fill-ratio proxy (contour area vs. minimum-enclosing-circle area), not a
    model confidence -- a real disk silhouette should be close to 1.0; a
    lower value flags a partially occluded/cut-off blob without rejecting it
    outright (the circularity gate already did the hard rejection).

    Identify-by-exclusion: if the strict per-color search finds exactly one
    of the two disks, tries a looser color net (EXCLUSION_LOWER/UPPER) for
    the other, searching only outside the confident disk's own region. See
    EXCLUSION_LOWER's comment for why this is safe (only fires on a strict
    1-of-2 result, shape gates unrelaxed) and why it's needed (direct glare
    desaturates this green paint toward grey, per 2026-09-17 user report).
    """
    if color_ranges is None:
        color_ranges = {
            "green": (GREEN_LOWER, GREEN_UPPER),
            "blue": (BLUE_LOWER, BLUE_UPPER),
        }

    candidates = prp.segment_disks_by_color(
        frame, color_ranges,
        min_radius=COLOR_DISK_MIN_RADIUS, max_radius=COLOR_DISK_MAX_RADIUS,
        min_circularity=COLOR_DISK_MIN_CIRCULARITY,
    )

    best_by_color = {}
    for color_name in color_ranges:
        same_color = [c for c in candidates if c["color"] == color_name]
        if same_color:
            best_by_color[color_name] = max(same_color, key=lambda c: c["area"])

    if len(best_by_color) == 1 and len(color_ranges) == 2:
        found_color = next(iter(best_by_color))
        missing_color = next(c for c in color_ranges if c != found_color)
        found = best_by_color[found_color]
        ex_cx, ex_cy = found["center"]
        exclude_radius = found["radius"] * 1.3

        broad = prp.segment_disks_by_color(
            frame, {missing_color: (EXCLUSION_LOWER, EXCLUSION_UPPER)},
            min_radius=COLOR_DISK_MIN_RADIUS, max_radius=COLOR_DISK_MAX_RADIUS,
            min_circularity=COLOR_DISK_MIN_CIRCULARITY,
        )
        broad = [
            c for c in broad
            if math.hypot(c["center"][0] - ex_cx, c["center"][1] - ex_cy) > exclude_radius
        ]
        if broad:
            best = max(broad, key=lambda c: c["area"])
            best["via_exclusion"] = True
            best_by_color[missing_color] = best

    disks = []
    for color_name, best in best_by_color.items():
        r = best["radius"]
        fill_ratio = best["area"] / (math.pi * r * r) if r > 0 else 0.0
        conf = float(min(fill_ratio, 1.0))
        if best.get("via_exclusion"):
            conf *= 0.5  # weaker signal -- color gate was relaxed to find this one
        disks.append({
            "center": best["center"],
            "radius": r,
            "marker_center": None,
            "conf": conf,
            "source": "color",
            "color": color_name,
            "via_exclusion": bool(best.get("via_exclusion", False)),
        })

    return disks


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

    # 1) No model to load -- position detection is detect_disks_color (HSV
    # contour) end to end.

    # 1b) Average background from a clean interval at the beggining of the filming
    # (still needed: backs the contour fallback -- scale_mm_per_px now comes
    # from detect_disks_color's own radius samples instead, see below).
    # puck_masker excludes any color-detected disk region per sampled frame
    # from the median instead of assuming the whole window is puck-free --
    # a puck already resting on the table (or moving too little) for the
    # entire clean_seconds window would otherwise get baked into the
    # "background" as if it were table surface (see CLAUDE.md Known bugs;
    # estimate_background_median's own docstring has the full mechanism).
    def _puck_masker(frame):
        return [(d["center"][0], d["center"][1], d["radius"]) for d in detect_disks_color(frame)]

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
    cap = cv2.VideoCapture(str(video_path))
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
    # Collect several color-sourced radii and take the median instead of
    # locking scale from a single first detection — a single frame's radius
    # reading can be off (partial occlusion, glare), which would otherwise
    # corrupt scale_mm_per_px (and therefore every mm value in the output)
    # for the entire run from one bad frame.
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

        # 4) Primary detection: HSV color-contour
        disks = detect_disks_color(frame)
        disks = remove_duplicate_detections(disks)

        # 4b) Hybrid fallback: if the color detector missed a disk, look for
        # it via background subtraction, but only in the region where it was
        # last seen (not the whole frame) so we don't reintroduce contour
        # noise everywhere.
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

        # 5) Compute scale from the median of several color-sourced radii
        # (never from a contour_fallback radius -- see fallback_contour_disks:
        # don't let a fallback-quality measurement corrupt the one-time scale
        # calibration).
        if scale_mm_per_px is None:
            for d in disks:
                if d.get("source") == "color" and d["radius"] > 0:
                    radius_samples.append(float(d["radius"]))
            if len(radius_samples) >= RADIUS_SAMPLE_TARGET:
                median_rpx = float(np.median(radius_samples))
                scale_mm_per_px = DISK_DIAMETER_MM / (2.0 * median_rpx)
                info("Info", f"Computed scale: {scale_mm_per_px:.3f} mm/px "
                              f"(median of {len(radius_samples)} radius samples)")

        # 6) Resolve marker position + disk identity per disk (HSV)
        frame_dets = []
        for d in disks:
            cx_px, cy_px = d["center"]
            r_px = float(d["radius"])

            mark, marker_color = resolve_marker(frame, d, scale_mm_per_px)

            # 7) Drawing (disk & marker) on the original video
            # Green edge = color-contour detection, orange edge = contour fallback (debug aid)
            edge_color = (0, 255, 0) if d.get("source") == "color" else (0, 140, 255)
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
                "marker_color": marker_color,
                "source": d.get("source", "color"),
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
                det["marker_color"],
                det["source"],
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
            "r_px", "marker_color", "source"
        ])
        writer.writerows(all_detections)

    info("Done", f"Saved {len(all_detections)} detections to disk_tracks.csv")
    return
