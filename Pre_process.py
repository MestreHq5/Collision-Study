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


def detect_marker_center(
    frame: np.ndarray,
    disk_center: Tuple[float, float],
    disk_radius: float,
    hsv_lower: np.ndarray,
    hsv_upper: np.ndarray,
    pad_factor: float = 2,
    min_area: float = 10,
    min_circularity: float = 0.0,
    max_circularity: float = 1.0,
    mask_center: Optional[Tuple[float, float]] = None,
    mask_radius: Optional[float] = None,
    mask_inner_radius: float = 0.0
) -> Optional[Tuple[int, int]]:
    """
    Crop around `disk_center` ± pad_factor×radius, threshold in HSV between
    hsv_lower/hsv_upper, clean the mask, and return the (x,y) centroid of
    the largest blob above `min_area`, or None if none found.

    Args:
      frame:        Full BGR image.
      disk_center:  (x,y) in pixels of the disk's centroid.
      disk_radius:  radius in pixels of the disk.
      hsv_lower:    lower HSV bound for the mark.
      hsv_upper:    upper HSV bound for the mark.
      debug:        If True, show debug windows for ROI/masks.
      pad_factor:   How much to pad the ROI around the disk.
      min_area:     Minimum contour area (px²) to accept as the mark.
      min_circularity: Minimum 4*pi*area/perimeter^2 to accept as the mark.
        The real paint marker is a compact round dot; a thin rim/shadow
        sliver (from an HSV floor loose enough to catch edge/glare noise)
        follows the disk's boundary arc instead and reads as a much less
        circular blob at comparable area. Default 0.0 keeps old behavior.
      max_circularity: Reject anything MORE circular than this. Confirmed
        real markers measured 0.72-0.83; a small (~28px) noise/compression
        artifact measured 0.943 — more "perfectly" round than real paint
        under real camera noise ever was. Default 1.0 keeps old behavior
        (no ceiling).
      mask_center, mask_radius: geometry used for the "must be inside the
        disk" restriction (step 3). Defaults to disk_center/disk_radius.
        Pass these separately when `disk_center` is really a search anchor
        that isn't guaranteed to sit on the disk (e.g. a keypoint) — without
        this, an anchor near/past the true edge lets the mask leak into
        background around the disk, matching whatever's out there instead of
        being confined to the puck itself.
      mask_inner_radius: also exclude anything closer than this to
        mask_center, turning the "inside disk" circle into an annulus. The
        offset marker sits near the disk's edge by design — excluding the
        center rejects near-center noise/highlights outright instead of
        relying on area/circularity alone. Default 0.0 keeps old behavior
        (filled circle, no inner exclusion).

    Returns:
      (x,y) pixel coordinates of the mark's centroid in full frame, or None.
    """
    if mask_center is None:
        mask_center = disk_center
    if mask_radius is None:
        mask_radius = disk_radius
    
    # 1) ROI extraction 
    x_c, y_c = map(int, disk_center) # convert pixel values to integers
    pad = int(disk_radius * pad_factor) # compute a reasonable extent for the ROI (padding)
    h, w = frame.shape[:2] # get frame dimensions
    
    
    x1, y1 = max(x_c - pad, 0), max(y_c - pad, 0) # Clamped to the (0,0) --> position of the upper-left corner
    x2, y2 = min(x_c + pad, w), min(y_c + pad, h) # Clamped to the (w,h) --> position of the lower-right corner (image restriction)
    
    roi = frame[y1:y2, x1:x2] # ROI in-frame image

    # 2) Pre‑smooth the ROI to mitigate motion blur, then convert to HSV
    roi_blur = cv2.GaussianBlur(roi, (5, 5), 0)
    hsv = cv2.cvtColor(roi_blur, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)

    # CLAHE on both Value AND Saturation. Under dimmer lighting, colored
    # markers lose saturation as well as brightness, and an absolute S
    # floor (e.g. S>=80) can reject a marker that would otherwise be a
    # perfectly clear hue match. Equalizing S helps recover that signal
    # without having to keep loosening the raw hsv_lower/upper bounds.
    # Tile grid must scale with the ROI: a fixed (8,8) grid on a marker-sized
    # crop (roughly disk_radius*pad_factor*2 px wide) gives tiles only a few
    # px across, which is too small a sample for local histogram equalization
    # — it amplifies sensor noise on the flat gray disk body into fake,
    # fully-saturated "color" blobs instead of just rescuing a dim real
    # marker. Keep tiles at least ~16px so equalization has enough signal.
    roi_h, roi_w = v.shape[:2]
    tiles_x = max(1, min(8, roi_w // 16))
    tiles_y = max(1, min(8, roi_h // 16))
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(tiles_x, tiles_y))
    v = clahe.apply(v)
    s = clahe.apply(s)
    hsv = cv2.merge((h, s, v))
    raw_mask = cv2.inRange(hsv, hsv_lower, hsv_upper)

    # 2b) Fallback: if the strict mask found (almost) nothing, relax the
    # S/V floors while keeping the hue window fixed. Hue is far more
    # lighting-invariant than S/V, so this recovers dim-but-correctly-hued
    # markers instead of silently returning None for the whole clip.
    if cv2.countNonZero(raw_mask) < min_area:
        lower_relaxed = hsv_lower.copy()
        upper_relaxed = hsv_upper.copy()
        lower_relaxed[1] = max(20, int(hsv_lower[1]) - 50)   # S floor
        lower_relaxed[2] = max(20, int(hsv_lower[2]) - 50)   # V floor
        raw_mask = cv2.inRange(hsv, lower_relaxed, upper_relaxed)

    # 3) Restrict to inside the disk (using mask_center/mask_radius, which may
    # differ from the crop's own disk_center/disk_radius anchor — see above),
    # and outside mask_inner_radius if given (annulus, not filled circle).
    mask_cx = int(mask_center[0]) - x1
    mask_cy = int(mask_center[1]) - y1
    mask_disk = np.zeros_like(raw_mask)
    cv2.circle(mask_disk, (mask_cx, mask_cy), int(mask_radius), 255, -1)
    if mask_inner_radius > 0:
        cv2.circle(mask_disk, (mask_cx, mask_cy), int(mask_inner_radius), 0, -1)
    raw_mask = cv2.bitwise_and(raw_mask, mask_disk)
    
    # 4) Blur and Morphological Cleanup
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


    # 5) Find Contours --> as seen already on segment_disks()
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None 

    # 6) Pick the largest contour that ALSO passes the shape gate — not simply
    # the largest contour, checked for shape after the fact. Measured a real
    # case where morphological CLOSE (needed to fill gaps within a genuine
    # marker blob) fused the marker together with adjacent background/shadow
    # into one large, irregular blob (circ ~0.15, correctly rejected) while a
    # separate small round blob (the actual marker, ~40px, circ ~0.74) sat
    # right next to it in the same mask — picking "largest" grabbed the fused
    # blob, failed its circularity check, and threw away the whole detection
    # without ever looking at the valid smaller one. Filter to valid
    # candidates first, then take the largest among those.
    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        if min_circularity > 0 or max_circularity < 1.0:
            perimeter = cv2.arcLength(c, True)
            circularity = (4 * np.pi * area / (perimeter * perimeter)) if perimeter > 0 else 0.0
            if circularity < min_circularity or circularity > max_circularity:
                continue
        candidates.append((area, c))

    if not candidates:
        return None
    marker = max(candidates, key=lambda t: t[0])[1]

    M = cv2.moments(marker) # Zeroth-order and first-order moments
    if M["m00"] == 0:
        return None

    # 7 Map centroid positions from ROI ---> full frame
    cx = int(M["m10"] / M["m00"]) + x1
    cy = int(M["m01"] / M["m00"]) + y1
    return (cx, cy)


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