'''
A list of usefull functions for initial transformation
Function based aproach

'''

import os
from typing import Tuple, Union, List, Dict, Optional

import cv2
import numpy as np




def estimate_background_median(
    video_path: str,
    clean_seconds: float,
    frame_sample_limit: int = 50,
    blur_kernel: Tuple[int, int] = (5, 5),
    output_path: str = "table_background.png",
    return_image: bool = False
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
    # --- 1) Open and validate video ---
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        raise ValueError(f"Invalid FPS detected ({fps}).")

    max_clean_frames = int(fps * clean_seconds)
    if max_clean_frames < 1:
        cap.release()
        raise ValueError(f"clean_seconds too small ({clean_seconds}s yields 0 frames).")

    num_samples = min(frame_sample_limit, max_clean_frames)
    if num_samples < 1:
        cap.release()
        raise ValueError(f"frame_sample_limit must be ≥1 (got {frame_sample_limit}).")

    # --- 2) Sample frames evenly ---
    frame_indices = np.linspace(0, max_clean_frames - 1, num_samples, dtype=int)
    frames = []
    for idx in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
    cap.release()

    if not frames:
        raise RuntimeError("No frames read for background estimation.")

    if len(frames) < num_samples:
        print(f"Warning: only {len(frames)} / {num_samples} frames were read.")

    # --- 3) Compute median background ---
    bg_median = np.median(np.stack(frames, axis=0), axis=0).astype(np.uint8)

    # --- 4) Optional blur to smooth out noise ---
    if blur_kernel is not None:
        kx, ky = blur_kernel
        if kx % 2 == 0 or ky % 2 == 0:
            raise ValueError("Blur kernel dimensions must be odd integers.")
        bg_median = cv2.GaussianBlur(bg_median, (kx, ky), 0)

    # --- 5) Save to disk (making dirs if needed) ---
    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    success = cv2.imwrite(output_path, bg_median)
    if not success:
        raise IOError(f"Failed to write background image to {output_path}")

    # --- 6) Return result ---
    if return_image:
        return output_path, bg_median
    return output_path


def segment_disks(
    frame: np.ndarray,
    background: np.ndarray,
    thresh_val: Union[int, float] = 50,
    use_otsu: bool = False,
    morph_kernel: Tuple[int, int] = (5, 5),
    min_radius: float = 45,
    max_radius: float = 65
) -> List[Dict]:
    """
    Subtracts `background` from `frame`, thresholds the difference, cleans it up,
    finds disk‐shaped contours, and returns their centers & radii in pixels.

    Args:
      frame:         Current BGR video frame (HxWx3).
      background:    Same‐shape BGR median background image.
      thresh_val:    Fixed threshold level (0–255). Ignored if use_otsu=True.
      use_otsu:      If True, use Otsu’s method to pick thresh_val automatically.
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

    # 2) Threshold
    if use_otsu:
        _, bin_mask = cv2.threshold(
            gray, 0, 255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
    else:
        _, bin_mask = cv2.threshold(
            gray, thresh_val, 255,
            cv2.THRESH_BINARY
        )

    # 3) Morphological open to clean
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, morph_kernel)
    clean = cv2.morphologyEx(bin_mask, cv2.MORPH_OPEN, kernel)

    # 4) Find contours
    contours, _ = cv2.findContours(
        clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    disks = []
    for cnt in contours:
        # 4a) Minimum enclosing circle
        (x, y), r = cv2.minEnclosingCircle(cnt)
        if not (min_radius <= r <= max_radius):
            continue

        # 4b) Optionally filter by circularity
        area = cv2.contourArea(cnt)
        perimeter = cv2.arcLength(cnt, True)
        if perimeter <= 0:
            continue
        circularity = 4 * np.pi * area / (perimeter * perimeter)
        if circularity < 0.7:  # tweak threshold if needed
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
    debug: bool = False,
    pad_factor: float = 2,
    min_area: float = 10
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

    Returns:
      (x,y) pixel coordinates of the mark's centroid in full frame, or None.
    """
    x_c, y_c = map(int, disk_center)
    pad = int(disk_radius * pad_factor)
    h, w = frame.shape[:2]
    x1, y1 = max(x_c - pad, 0), max(y_c - pad, 0)
    x2, y2 = min(x_c + pad, w), min(y_c + pad, h)
    roi = frame[y1:y2, x1:x2]

    # Convert to HSV and threshold
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    raw_mask = cv2.inRange(hsv, hsv_lower, hsv_upper)
    if debug:
        cv2.imshow("ROI", roi)
        cv2.imshow("Raw Mask", raw_mask)

    # Clean up mask
    mask = cv2.medianBlur(raw_mask, 5)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    if debug:
        cv2.imshow("Clean Mask", mask)
        cv2.waitKey(1)

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Pick the largest contour and check area
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < min_area:
        return None

    M = cv2.moments(c)
    if M["m00"] == 0:
        return None

    # Compute centroid and map back to full frame coords
    cx = int(M["m10"] / M["m00"]) + x1
    cy = int(M["m01"] / M["m00"]) + y1
    return (cx, cy)