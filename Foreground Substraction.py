import cv2
import numpy as np

def remove_background(
    video_path: str,
    bg_path: str,
    output_path: str,
    table_mask_path: str = None,
    threshold: int = 30
) -> str:
    """
    Reads `video_path`, subtracts the static background in `bg_path`,
    masks out anything outside `table_mask_path` (if given),
    writes a new video to `output_path` where only the moving
    foreground remains (background set to black),
    and returns the path to the saved video.
    """
    # Load static background (gray)
    bg_static = cv2.imread(bg_path, cv2.IMREAD_GRAYSCALE)
    if bg_static is None:
        raise FileNotFoundError(f"Could not load background image: {bg_path}")

    # Load & binarize table mask (if provided)
    if table_mask_path:
        tm = cv2.imread(table_mask_path, cv2.IMREAD_GRAYSCALE)
        if tm is None:
            raise FileNotFoundError(f"Could not load table mask: {table_mask_path}")
        _, table_mask = cv2.threshold(tm, 127, 255, cv2.THRESH_BINARY)
    else:
        table_mask = None

    # Open input video & prepare output writer
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {video_path}")

    fps    = cap.get(cv2.CAP_PROP_FPS)
    w_vid  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h_vid  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out    = cv2.VideoWriter(output_path, fourcc, fps, (w_vid, h_vid))

    # Precompute morphology kernels
    k_open  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9,9))

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Gray + optional mask
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if table_mask is not None:
            if table_mask.shape != gray.shape:
                table_mask = cv2.resize(table_mask, (gray.shape[1], gray.shape[0]))
            gray = cv2.bitwise_and(gray, table_mask)

        # Background subtraction
        fg_diff = cv2.absdiff(gray, bg_static)
        _, fg_bin = cv2.threshold(fg_diff, threshold, 255, cv2.THRESH_BINARY)

        # Clean up
        fg = cv2.morphologyEx(fg_bin, cv2.MORPH_OPEN,  k_open)
        fg = cv2.morphologyEx(fg,     cv2.MORPH_CLOSE, k_close)

        # Mask original frame and write
        fg_color = cv2.bitwise_and(frame, frame, mask=fg)
        out.write(fg_color)

    cap.release()
    out.release()

    print(f"Saved foreground video to {output_path}")
    return output_path


