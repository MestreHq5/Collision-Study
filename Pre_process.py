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
    for idx in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if ret:
            
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

    
    # 3) Compute median background ---
    bg_median = np.median(np.stack(frames, axis=0), axis=0).astype(np.uint8)

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

    # 2) Threshold using a manual 'optimal' value    
    _, bin_mask = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)


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
      
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)) # Perform CLAHE contrast enhancement
    v = clahe.apply(v)
    hsv = cv2.merge((h, s, v)) # merge the new CLAHE enhanced V chanel
    raw_mask = cv2.inRange(hsv, hsv_lower, hsv_upper) 

    # 3) Restrict to inside the disk
    center_x = x_c - x1
    center_y = y_c - y1
    mask_disk = np.zeros_like(raw_mask)
    cv2.circle(mask_disk, (center_x, center_y), int(disk_radius), 255, -1)
    raw_mask = cv2.bitwise_and(raw_mask, mask_disk)
    
    # 4) Blur and Morphological Cleanup
    mask = cv2.medianBlur(raw_mask, 5)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7,7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)


    # 5) Find Contours --> as seen already on segment_disks()
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None 

    # 6) Pick the largest contour and check area
    marker = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(marker)
    if area < min_area:
        return None

    M = cv2.moments(marker) # Zeroth-order and first-order moments
    if M["m00"] == 0:
        return None

    # 7 Map centroid positions from ROI ---> full frame
    cx = int(M["m10"] / M["m00"]) + x1
    cy = int(M["m01"] / M["m00"]) + y1
    return (cx, cy)