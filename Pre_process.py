'''
A list of usefull functions for initial transformation
Function based aproach

'''

import os
from typing import Tuple, Union, List, Dict, Optional, Callable

import cv2
import numpy as np


def estimate_background_median(
    video_path: str,
    clean_seconds: float,
    frame_sample_limit: int = 50,
    blur_kernel: Tuple[int, int] = (5, 5),
    output_path: str = "table_background.png",
    return_image: bool = False,
    puck_masker: Optional[Callable] = None,
) -> Union[str, Tuple[str, np.ndarray]]:

    """
    Estimate a stable background image by taking the per-pixel median
    of up to `frame_sample_limit` frames sampled evenly over the first
    `clean_seconds` of the video.

    Args:
        video_path:         Path to the input video file.
        clean_seconds:      Duration (in seconds) from the start of the video
                            to sample frames for the background.
        frame_sample_limit: Maximum number of frames to sample for the median.
        blur_kernel:        Gaussian blur kernel size (must be odd integers).
                            Set to None to disable blurring.
        output_path:        Where to save the background image.
        return_image:       If True, also return the background array.
        puck_masker:         Optional callable(frame) -> list of (cx, cy, r)
                            puck circles detected in that sampled frame. When
                            given, those regions are excluded per-frame from
                            the median instead of assumed clean -- a plain
                            per-pixel median only tolerates a puck covering a
                            given pixel in <50% of the sampled frames, so a
                            puck already resting on the table (or moving too
                            little) during the whole `clean_seconds` window
                            gets silently baked into the "background" as if
                            it were table surface, corrupting the contour
                            fallback's background subtraction for the entire
                            run (see CLAUDE.md Known bugs). Wherever every
                            sampled frame has that pixel masked (no clean
                            sample anywhere), falls back to the plain,
                            unmasked median there rather than leaving a hole.

    Returns:
        If return_image is False:
          str: Path to the saved background image.
        If return_image is True:
          Tuple[str, np.ndarray]: (path, background_image_array)

    Raises:
        IOError:     If the video can’t be opened or the image can’t be saved.
        ValueError:  If fps is invalid, or parameters are out of range.
        RuntimeError:If no frames could be read for the background.
    """
    
    # 1) Open and validate video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        raise ValueError(f"Invalid FPS detected ({fps}).")

    max_clean_frames = int(fps * clean_seconds)
    if max_clean_frames < 6:
        cap.release()
        raise ValueError(f"Number of clean_seconds is too small ({clean_seconds}s yields less than 6 frames).")

    num_samples = min(frame_sample_limit, max_clean_frames)


    # 2) Sample frames evenly
    frame_indices = np.linspace(0, max_clean_frames - 1, num_samples, dtype=int)
    frames = []
    puck_masks = []  # per-frame bool mask, True where a puck was detected (only if puck_masker given)
    for idx in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if ret:

            if puck_masker is not None:
                mask = np.zeros(frame.shape[:2], dtype=bool)
                for cx, cy, r in puck_masker(frame):
                    cv2.circle(mask, (int(cx), int(cy)), int(r), True, -1)  # type: ignore[arg-type]
                puck_masks.append(mask)

            # Apply Gaussian Blur to every frame
            if blur_kernel is not None:
                kx, ky = blur_kernel
                frame_blured = cv2.GaussianBlur(frame, (kx, ky), 0)
                frames.append(frame_blured)

            else:
                frames.append(frame)

    cap.release()

    if not frames:
        raise RuntimeError("No frames read for background estimation.")

    if len(frames) < num_samples:
        # Warning: Not fatal, but suggests another try of the experiment
        print(f"Warning: only {len(frames)} / {num_samples} frames were read.")


    # 3) Compute median background. Start from the plain per-pixel median
    # (fast baseline, also the fallback for step 3b below), then, if
    # puck_masker found anything, recompute just the pixels a puck ever
    # covered using only the frames where that specific pixel was clean --
    # a plain median only tolerates a puck covering a given pixel in <50% of
    # samples, so a puck already resting on the table for the whole
    # clean_seconds window would otherwise get baked into the "background"
    # as if it were table surface (see docstring). Restricted to the
    # (typically small, puck-footprint-sized) occluded region rather than a
    # full-frame masked/nanmedian pass: doing this densely over the whole
    # frame via np.nanmedian was tried and blew past several GB of memory on
    # a 1080p stack (numpy's nanmedian falls back to a masked-array sort
    # internally, which is not memory-lean) for no benefit, since almost all
    # pixels are never touched by a puck at all.
    stack = np.stack(frames, axis=0)  # uint8, (N, H, W, 3)
    bg_median = np.median(stack, axis=0).astype(np.uint8)

    if puck_masks and any(m.any() for m in puck_masks):
        mask_stack = np.stack(puck_masks, axis=0)  # (N, H, W) bool
        occluded_any = mask_stack.any(axis=0)
        ys, xs = np.nonzero(occluded_any)
        for y, x in zip(ys, xs):
            clean_frames = ~mask_stack[:, y, x]
            if clean_frames.any():
                bg_median[y, x] = np.median(stack[clean_frames, y, x], axis=0).astype(np.uint8)
            # else: puck covered every sample at this pixel -- no clean data
            # anywhere, keep the plain-median fallback already in bg_median.

    # 4) Save to disk (making dirs if needed) ---
    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    success = cv2.imwrite(output_path, bg_median)
    if not success:
        raise IOError(f"Failed to write background image to {output_path}")

    # 6) Return result
    if return_image:
        return output_path, bg_median
    return output_path


def segment_disks(  
    frame: np.ndarray,
    background: np.ndarray, # Computed earlier on estimate_background_median
    thresh_val: Union[int, float] = 50,
    morph_kernel: Tuple[int, int] = (5, 5),
    min_radius: float = 45,
    max_radius: float = 65,
    use_otsu: bool = False,
) -> List[Dict]:
    """
    Subtracts `background` from `frame`, thresholds the difference, cleans it up,
    finds disk‐shaped contours, and returns their centers & radius in pixels.

    Args:
      frame:         Current BGR video frame (H, W, 3).
      background:    Same‐shape BGR median background image.
      thresh_val:    Fixed threshold level (0–255). Ignored if use_otsu=True.
      morph_kernel:  Kernel size for morphological open to remove noise.
      min_radius:    Discard detections smaller than this radius [px].
      max_radius:    Discard detections larger than this radius [px].

    Returns:
      A list of dicts, each with:
        - "contour": np.ndarray of the contour points
        - "center":  (float x, float y)
        - "radius":  float radius in pixels
    """
    # 1) Background subtraction → gray diff
    diff = cv2.absdiff(frame, background)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

    # 2) Threshold. Fixed value by default, but fall back to (or force) an
    #    adaptive Otsu threshold when contrast is too low for a fixed cut
    #    to separate disks from background reliably (e.g. reduced lighting).
    if use_otsu:
        otsu_val, bin_mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        _, bin_mask = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)
        # Safety net: if almost nothing passed the fixed threshold (typical
        # symptom of a dimmer scene), recompute with Otsu instead of
        # silently returning zero/near-zero detections for the frame.
        if cv2.countNonZero(bin_mask) < 50:
            _, bin_mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)


    # 3) Morphological open then close to clean and fill any holes or clear any specles
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, morph_kernel)
    clean = cv2.morphologyEx(bin_mask, cv2.MORPH_OPEN, kernel)
    clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, kernel)

    # 4) Find contours
    contours, _ = cv2.findContours(
        clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    # 5) Filter contours based on radious and circularity 
    disks = []
    for cnt in contours:
        # First test:  Minimum enclosing circle
        (x, y), r = cv2.minEnclosingCircle(cnt)
        if not (min_radius <= r <= max_radius):
            continue

        # Second test: Filter by circularity
        area = cv2.contourArea(cnt)
        perimeter = cv2.arcLength(cnt, True)
        if perimeter <= 0:
            continue
        circularity = 4 * np.pi * area / (perimeter * perimeter)
        if circularity < 0.7:  # Optimize if needed (0.7 seems fine from the tests made)
            continue

        disks.append({
            "contour": cnt,
            "center": (x, y),
            "radius": r
        })

    return disks


def segment_disks_by_color(
    frame: np.ndarray,
    color_ranges: Dict[str, Tuple[np.ndarray, np.ndarray]],
    min_radius: float = 30,
    max_radius: float = 120,
    min_circularity: float = 0.75,
    morph_kernel: Tuple[int, int] = (7, 7),
) -> List[Dict]:
    """
    Position detection via direct HSV color-range matching instead of
    background subtraction (segment_disks). Only viable because the disks
    themselves are painted a large, saturated, matte color (see CLAUDE.md
    "Marker detection") -- against a gray disk body there'd be no whole-disk
    color signal to threshold on.

    Unlike segment_disks, this doesn't need a background image or care about
    ambient brightness drifting between frames -- it only asks whether a
    pixel's hue/saturation falls in a calibrated color window, so it isn't
    fooled by a glare patch reading as "changed from background" the way
    background subtraction is.

    Searches each color independently (one HSV mask per entry in
    color_ranges), so a detection's `color` comes directly from which mask
    it was found in -- no separate bulk-color vote needed to know identity,
    unlike the marker scheme's classify_disk_bulk_color (which still runs
    separately for the *marker* dimple search, unaffected by this).

    Args:
      color_ranges: dict of name -> (hsv_lower, hsv_upper), e.g.
        {"green": (GREEN_LOWER, GREEN_UPPER), "blue": (...)}
      min_radius/max_radius: plausible disk radius in px (min-enclosing-circle
        based) -- placeholder bounds for this camera's framing, same caveat
        as segment_disks' own min/max_radius: retune per camera setup.
      min_circularity: rejects thin rim/sliver artifacts same as the marker
        shape gates elsewhere in this file -- a real disk silhouette is
        close to a filled circle.

    Returns a list of dicts, each with "contour", "center", "radius", "color",
    "area" -- one entry per contour that passed the gates (may be more than
    one per color; caller picks e.g. the largest as the real disk).
    """
    disks = []
    for color_name, (lower, upper) in color_ranges.items():
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower, upper)
        mask = cv2.medianBlur(mask, 5)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, morph_kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            (x, y), r = cv2.minEnclosingCircle(cnt)
            if not (min_radius <= r <= max_radius):
                continue
            area = cv2.contourArea(cnt)
            perimeter = cv2.arcLength(cnt, True)
            if perimeter <= 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            if circularity < min_circularity:
                continue
            disks.append({
                "contour": cnt,
                "center": (x, y),
                "radius": r,
                "color": color_name,
                "area": area,
            })

    return disks


def _select_best_blob(raw_mask, x1, y1, mask_center, mask_radius, mask_inner_radius,
                       disk_radius, min_area, min_circularity, max_circularity,
                       max_area=None):
    """
    Shared back half of marker detection: restrict a candidate pixel mask to
    inside the disk (annulus if mask_inner_radius given), clean it up, and
    pick the largest contour that ALSO passes the shape gate -- not simply
    the largest contour, checked for shape after the fact (measured a real
    case where morphological CLOSE fused the marker together with adjacent
    background/shadow into one large, irregular blob that correctly failed
    circularity, while a separate small round blob -- the actual marker --
    sat right next to it in the same mask and was never even considered).

    Called by detect_dark_marker_center; split out as its own function so
    the geometry-restriction/cleanup/selection logic is separate from how
    `raw_mask` itself gets built (darkness threshold).

    raw_mask: candidate pixel mask (uint8, 0/255), already in ROI/crop
      coordinates (crop's top-left corner is (x1, y1) in full-frame coords).
    mask_center, mask_radius, mask_inner_radius, disk_radius,
    min_area, min_circularity, max_circularity: see detect_dark_marker_center.
    max_area: reject anything LARGER than this too (px^2), default None (no
      cap). detect_dark_marker_center's relaxed retry pass needs this:
      loosening a relative-darkness threshold risks catching a patch of the
      disk that got uniformly darker (shadow/exposure dip) rather than the
      compact marker dimple, and a near-disk-sized dark patch can still be
      circular enough to pass the shape gate on its own -- only a size cap
      rules that out.
    """
    # Restrict to inside the disk (using mask_center/mask_radius, which may
    # differ from the crop's own disk_center/disk_radius anchor), and
    # outside mask_inner_radius if given (annulus, not filled circle).
    mask_cx = int(mask_center[0]) - x1
    mask_cy = int(mask_center[1]) - y1
    mask_disk = np.zeros_like(raw_mask)
    cv2.circle(mask_disk, (mask_cx, mask_cy), int(mask_radius), 255, -1)
    if mask_inner_radius > 0:
        cv2.circle(mask_disk, (mask_cx, mask_cy), int(mask_inner_radius), 0, -1)
    raw_mask = cv2.bitwise_and(raw_mask, mask_disk)

    # Blur and Morphological Cleanup
    mask = cv2.medianBlur(raw_mask, 5)
    # Kernel size scales with disk_radius instead of a fixed 7x7: on a disk this
    # small (e.g. a smaller/more distant marker, ~10px radius), a fixed 7x7 open
    # can erase the entire real marker blob (measured: a genuine 41px marker
    # blob went to 0px through a 7x7 open), not just noise specks. Same failure
    # mode as the CLAHE tile-size fix above — a pixel-count constant tuned for
    # one clip's object scale breaks on another's.
    morph_k = max(3, min(7, int(round(disk_radius * 0.3)) | 1))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_k, morph_k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue
        if min_circularity > 0 or max_circularity < 1.0:
            perimeter = cv2.arcLength(c, True)
            circularity = (4 * np.pi * area / (perimeter * perimeter)) if perimeter > 0 else 0.0
            if circularity < min_circularity or circularity > max_circularity:
                continue
        candidates.append((area, c))

    if not candidates:
        return None
    blob = max(candidates, key=lambda t: t[0])[1]

    M = cv2.moments(blob)  # Zeroth-order and first-order moments
    if M["m00"] == 0:
        return None

    # Map centroid position from ROI -> full frame
    cx = int(M["m10"] / M["m00"]) + x1
    cy = int(M["m01"] / M["m00"]) + y1
    return (cx, cy)


def detect_dark_marker_center(
    frame,
    disk_center,
    disk_radius,
    pad_factor: float = 2.0,
    min_area: float = 10,
    min_circularity: float = 0.0,
    max_circularity: float = 1.0,
    mask_center: Optional[Tuple[float, float]] = None,
    mask_radius: Optional[float] = None,
    mask_inner_radius: float = 0.0,
    dark_value_frac: float = 0.55,
    max_area: Optional[float] = None,
    relax_frac_delta: float = 0.0,
) -> Optional[Tuple[int, int]]:
    """
    Marker detection: the disk itself is painted a reliable, saturated
    color, and the offset marker is a black-painted dimple -- the marker's
    *only* distinguishing feature is that it's dark, so this finds the
    darkest compact blob within the disk instead of hunting a specific hue.
    A bright specular highlight works AGAINST a dark-marker match instead of
    mimicking a bright saturated one, which is structurally more robust to
    glare than hue-matching a small marker would be.

    Uses _select_best_blob for the shared crop extraction +
    geometry-restriction + contour selection; only the candidate-pixel rule
    is specific to this function (relatively dark, not a fixed hue range).

    dark_value_frac: pixels with V below this fraction of the crop's own
      median V (measured only inside the disk mask, so background outside
      the disk can't bias the threshold) count as "dark" -- relative, not
      an absolute cutoff, so it adapts to whatever lighting a given frame
      actually has.
    max_area: forwarded to _select_best_blob -- see its docstring. Required
      for a safe relax_frac_delta > 0 (see below): without a cap, a relaxed
      pass can mistake a patch of the disk that got uniformly darker (motion
      blur, a passing shadow, exposure dip) for the marker, since that patch
      can still be compact/circular enough to clear the shape gate on its
      own merit -- measured directly on real footage (`17.mp4`, disk green,
      frames ~205-213): raising dark_value_frac by ~0.30 over the calibrated
      value grew the "dark" region from 0px to >1000px as the WHOLE disk's
      median brightness dipped, not because the marker became visible.
    relax_frac_delta: if the strict `dark_value_frac` pass finds no
      shape-gate-passing blob, retries once with
      `dark_value_frac + relax_frac_delta` before giving up.
      0.0 (default) disables this -- opt in explicitly, and always pair with
      a real `max_area` when raising it (see above). Verified on the real
      `Camera Roll/New Disks/` batch with delta=0.10 + max_area capped at
      12% of the disk's face area (see detector.MARKER_RELAX_FRAC_DELTA/
      MARKER_MAX_AREA_FRAC): recovered several marginally-subtle real
      dimples with no regressions anywhere in the batch (blue recall jumped
      52-77% -> 95-100% on 3 clips; green stayed 100% where it already was),
      and on `17.mp4`'s frames ~205-212 -- exactly the "whole disk dipped
      darker" case this cap exists for -- correctly still returned None
      instead of the near-disk-sized false blob the relaxed threshold alone
      would have matched there. Not a fix for frames where the marker is
      truly not visible (motion blur mid-collision, or self-occluded by the
      disk's own rim from this side camera's angle at that rotation) -- those
      correctly stay None and get filled by interpolation instead of a guess
      (see Post_process.py's per-segment theta interpolation).

    Returns (x, y) centroid in full-frame coordinates, or None.
    """
    if mask_center is None:
        mask_center = disk_center
    if mask_radius is None:
        mask_radius = disk_radius

    x_c, y_c = map(int, disk_center)
    pad = int(disk_radius * pad_factor)
    h, w = frame.shape[:2]
    x1, y1 = max(x_c - pad, 0), max(y_c - pad, 0)
    x2, y2 = min(x_c + pad, w), min(y_c + pad, h)
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return None

    roi_blur = cv2.GaussianBlur(roi, (5, 5), 0)
    v = cv2.cvtColor(roi_blur, cv2.COLOR_BGR2HSV)[:, :, 2]

    mask_cx = int(mask_center[0]) - x1
    mask_cy = int(mask_center[1]) - y1
    disk_only = np.zeros(v.shape, dtype=np.uint8)
    cv2.circle(disk_only, (mask_cx, mask_cy), int(mask_radius), 255, -1)
    if mask_inner_radius > 0:
        cv2.circle(disk_only, (mask_cx, mask_cy), int(mask_inner_radius), 0, -1)

    disk_pixels_v = v[disk_only > 0]
    if disk_pixels_v.size == 0:
        return None
    median_v = float(np.median(disk_pixels_v))

    # Strict pass: no max_area cap here -- this threshold is already
    # calibrated against real markers (see dark_value_frac docstring) and
    # shouldn't newly reject a real detection just because a size cap
    # designed for the relaxed retry below happened to be tighter than some
    # legitimate marker's measured area.
    v_thresh = median_v * dark_value_frac
    raw_mask = ((v < v_thresh).astype(np.uint8)) * 255
    found = _select_best_blob(raw_mask, x1, y1, mask_center, mask_radius,
                               mask_inner_radius, disk_radius,
                               min_area, min_circularity, max_circularity)
    if found is not None or relax_frac_delta <= 0:
        return found

    # Single relaxed retry (see relax_frac_delta docstring) -- always paired
    # with max_area so a frame where the whole disk dipped darker (not just
    # the marker) can't get mistaken for it.
    v_thresh_relaxed = median_v * (dark_value_frac + relax_frac_delta)
    raw_mask_relaxed = ((v < v_thresh_relaxed).astype(np.uint8)) * 255
    return _select_best_blob(raw_mask_relaxed, x1, y1, mask_center, mask_radius,
                              mask_inner_radius, disk_radius,
                              min_area, min_circularity, max_circularity,
                              max_area=max_area)


def classify_disk_bulk_color(frame, disk_center, disk_radius, color_ranges,
                              pad_factor: float = 1.0, min_share: float = 0.15):
    """
    Disk identity: classifies which of color_ranges the disk's own BODY
    matches by majority vote over the disk's circular interior, instead of
    matching a small offset marker blob. This votes over hundreds/thousands
    of pixels instead of a handful, so isolated noise or a stray highlight
    can't flip the read the way it would for a small marker dot.

    Args:
      color_ranges: dict of name -> (hsv_lower, hsv_upper), e.g.
        {"green": (GREEN_LOWER, GREEN_UPPER), "blue": (BLUE_LOWER, BLUE_UPPER)}
      pad_factor: crop padding around disk_center, in disk_radius units --
        1.0 is enough here (unlike the marker searches) since this only
        ever looks *inside* disk_radius, never needs headroom past it.
      min_share: minimum fraction of the disk's interior a color must match
        to be accepted at all -- rejects "most votes of near-zero" when the
        disk isn't really a calibrated color that frame (or isn't really
        there).

    Returns the best-matching name, or None if nothing cleared min_share.
    """
    x_c, y_c = map(int, disk_center)
    pad = int(disk_radius * pad_factor)
    h, w = frame.shape[:2]
    x1, y1 = max(x_c - pad, 0), max(y_c - pad, 0)
    x2, y2 = min(x_c + pad, w), min(y_c + pad, h)
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return None

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask_cx, mask_cy = x_c - x1, y_c - y1
    disk_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    cv2.circle(disk_mask, (mask_cx, mask_cy), int(disk_radius), 255, -1)
    disk_area = int(cv2.countNonZero(disk_mask))
    if disk_area == 0:
        return None

    best_name, best_count = None, 0
    for name, (lower, upper) in color_ranges.items():
        color_mask = cv2.inRange(hsv, lower, upper)
        color_mask = cv2.bitwise_and(color_mask, disk_mask)
        count = cv2.countNonZero(color_mask)
        if count > best_count:
            best_count = count
            best_name = name

    if best_count < min_share * disk_area:
        return None
    return best_name


def calibrate_hsv_range(video_path: str, frame_index: int = 0, box: int = 6) -> None:
    """
    Interactive calibration tool. Opens a single frame from `video_path`;
    click on a marker dot and it prints the HSV of a small box around the
    click plus a suggested (lower, upper) np.array range you can paste
    straight into detector.py's GREEN_LOWER/UPPER or BLUE_LOWER/UPPER.

    Run this once per lighting setup (e.g. whenever the room light changes)
    instead of guessing new thresholds by hand.

    Controls: click marker -> prints range. Press 'q' to quit.
    """
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise IOError(f"Could not read frame {frame_index} from {video_path}")

    hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    window = "Click on the marker dot, then press q"

    def on_click(event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        y1, y2 = max(0, y - box), min(hsv_frame.shape[0], y + box)
        x1, x2 = max(0, x - box), min(hsv_frame.shape[1], x + box)
        patch = hsv_frame[y1:y2, x1:x2].reshape(-1, 3)
        lo = np.percentile(patch, 5, axis=0).astype(int)
        hi = np.percentile(patch, 95, axis=0).astype(int)
        # pad a bit and clamp to valid ranges
        lo = np.clip(lo - [5, 20, 20], 0, 255)
        hi = np.clip(hi + [5, 20, 20], 0, 255)
        print(f"Sampled at ({x},{y}):")
        print(f"  LOWER = np.array([{lo[0]}, {lo[1]}, {lo[2]}])")
        print(f"  UPPER = np.array([{hi[0]}, {hi[1]}, {hi[2]}])")

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_click)
    while True:
        cv2.imshow(window, frame)
        if cv2.waitKey(20) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()