# Use for results mix, total and regression

import math
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import os

# CSV and Excel Collums
REQ_COLS = ["frame","disk_id","cx_mm","cy_mm","mx_mm","my_mm","r_px"]



# --- 1. Force Qt to render High-DPI properly (MUST BE BEFORE MATPLOTLIB IMPORTS) ---
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

# --- 2. Imports ---
from pathlib import Path
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# --- 3. Default Matplotlib Resolution ---
plt.rcParams['figure.dpi'] = 150         # Screen DPI for popup window
plt.rcParams['savefig.dpi'] = 300        # Saved image DPI


# Helpers
def _ensure_sorted(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values("frame").reset_index(drop=True)


def _add_meter_cols(df_raw: pd.DataFrame) -> pd.DataFrame:
    df = df_raw.copy()
    df["cx"] = df["cx_mm"] / 1000.0
    df["cy"] = df["cy_mm"] / 1000.0
    df["mx"] = df["mx_mm"] / 1000.0
    df["my"] = df["my_mm"] / 1000.0
    return df


def _unwrap_angle(dfm: pd.DataFrame) -> np.ndarray:
    """
    Continuous unwrapped marker angle (radians), NaN wherever the marker
    wasn't detected that frame (mx/my come through as NaN from the CSV).

    np.unwrap does not skip NaN -- a single NaN in the input poisons every
    later value via unwrap's internal cumsum, e.g.
    unwrap([0,-1,-2,NaN,-4,-5,-6]) == [0,-1,-2,NaN,NaN,NaN,NaN] (verified).
    With marker recall as low as ~44-60% on real footage, nearly every
    segment hit its first gap early, so theta/omega were silently running on
    far less real data than they appeared to. Unwrap only the valid
    (non-NaN) subsequence in original frame order, then put NaN back at the
    gaps -- a gap of a few frames doesn't break unwrap's turn detection
    since rotation is slow (~1 deg/frame) relative to the pi wrap threshold.
    """
    dx = dfm["mx"] - dfm["cx"]
    dy = dfm["my"] - dfm["cy"]
    theta = np.arctan2(dy, dx).to_numpy()
    valid = np.isfinite(theta)
    out = np.full(theta.shape, np.nan, dtype=float)
    if valid.sum() >= 2:
        out[valid] = np.unwrap(theta[valid])
    elif valid.sum() == 1:
        out[valid] = theta[valid]
    return out


def _compute_vels(df_m: pd.DataFrame, fps: float) -> pd.DataFrame:
    """
    Finite-difference linear v, and angular speed from unwrapped marker angle.

    Divides by the actual elapsed frames (out["frame"].diff()), not a
    hardcoded 1 -- a disk missing from a frame gets no row at all (see
    detector.py's CSV export), not a NaN placeholder, so consecutive rows
    can legitimately be more than 1 frame apart. `.diff() * fps` alone
    assumes exactly 1 frame between every pair of consecutive rows and
    silently overstates velocity by the gap size whenever a real gap
    exists, feeding directly into restitution/momentum error and, via Vcm,
    the COM-frame energy calc's translational term too (see CLAUDE.md Known
    bugs, physics-metrics review).
    """
    out = df_m.copy()
    dframe = out["frame"].diff()
    # Linear finite differences (m/s), aligned to later frame
    out["vx"] = out["cx"].diff() / dframe * fps
    out["vy"] = out["cy"].diff() / dframe * fps

    # Angular from marker vector (NaN-safe unwrap, see _unwrap_angle)
    theta_unwrapped = _unwrap_angle(out)                # radians
    dtheta = np.full(len(out), np.nan, dtype=float)    # length N
    if len(out) > 1:
        dtheta[1:] = np.diff(theta_unwrapped)          # put N-1 diffs starting at index 1
    out["omega_deg_s"] = np.degrees(dtheta) / dframe.to_numpy() * fps  # deg/s, aligned to later frame
    out["theta_unwrapped_deg"] = np.degrees(theta_unwrapped)  # for students
    return out


def _sigma_clip_linear_fit(x: np.ndarray, y: np.ndarray, n_sigma: float = 2.5,
                            max_iters: int = 10, min_points: int = 4):
    """
    Iterative sigma-clipping linear regression of y vs x (refits after each
    clip so an early outlier can't drag the trend and shield a later one).

    Returns (slope, intercept, inlier_mask, residual_std): inlier_mask is
    aligned to the input arrays and True only for points that both exist
    (finite) and survived clipping. residual_std is the final inlier set's
    residual standard deviation against the returned fit -- a low value
    means the surviving "inliers" are genuinely tightly clustered around a
    trend; a high one means sigma-clipping converged on a self-consistent
    but loosely-scattered fit, which is a real, measured failure mode: on a
    real, noisy segment (240_25.mp4 disk 1) this returned "0 outliers" with
    a residual_std of ~79 deg -- clipping only rejects points that stand
    out *relative to the fit's own noise floor*, so if that floor is
    already huge because much of the "inlier" data is itself poor, nothing
    looks like an outlier anymore. Callers that need to trust this fit for
    extrapolation (not just a rough slope estimate) should gate on this,
    not just "0 outliers" -- see detector.py's recovery-confidence gate.
    slope/intercept/residual_std are NaN if fewer than min_points finite
    points are available to fit at all.
    """
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < min_points:
        return np.nan, np.nan, mask, np.nan

    for _ in range(max_iters):
        idx = np.flatnonzero(mask)
        slope, intercept = np.polyfit(x[idx], y[idx], 1)
        resid = y[idx] - (slope * x[idx] + intercept)
        sigma = float(np.std(resid))
        if sigma < 1e-9:
            break
        keep = np.abs(resid) <= n_sigma * sigma
        if keep.all():
            break
        if keep.sum() < min_points:
            break  # don't clip below the floor -- keep the prior mask/fit
        new_mask = np.zeros_like(mask)
        new_mask[idx] = keep
        mask = new_mask

    idx = np.flatnonzero(mask)
    slope, intercept = np.polyfit(x[idx], y[idx], 1)
    residual_std = float(np.std(y[idx] - (slope * x[idx] + intercept)))
    return float(slope), float(intercept), mask, residual_std


def _wrap_pi(a: np.ndarray) -> np.ndarray:
    """Wrap radians into (-pi, pi]."""
    return (a + np.pi) % (2 * np.pi) - np.pi


def _robust_omega_seed(frame: np.ndarray, theta_wrapped: np.ndarray,
                        max_gap: float = 20, max_pairs_per_point: int = 5) -> float:
    """
    Initial angular-velocity estimate (rad/frame), robust by construction:
    the median of wrapped pairwise angular differences between valid
    samples separated by at most max_gap frames (true rotation is slow,
    ~1 deg/frame, so a gap this small can't itself be ambiguous mod 2*pi).
    Deliberately never runs a global sequential unwrap for this seed -- see
    _robust_unwrap_and_fit for why that matters.
    """
    idx = np.flatnonzero(np.isfinite(theta_wrapped))
    slopes = []
    for i in range(len(idx)):
        for j in range(i + 1, min(i + 1 + max_pairs_per_point, len(idx))):
            gi, gj = idx[i], idx[j]
            gap = frame[gj] - frame[gi]
            if gap <= 0 or gap > max_gap:
                continue
            dtheta = _wrap_pi(theta_wrapped[gj] - theta_wrapped[gi])
            slopes.append(dtheta / gap)
    return float(np.median(slopes)) if slopes else np.nan


def _robust_unwrap_and_fit(frame: np.ndarray, theta_wrapped: np.ndarray,
                            n_sigma: float = 2.5, max_iters: int = 10,
                            min_points: int = 4, refine_rounds: int = 3):
    """
    Branch-robust unwrap + sigma-clipped linear fit of theta vs. frame,
    combined because they turned out not to be separable: a naive
    "sequential np.unwrap first, sigma-clip second" pipeline was tested
    against a synthetic segment with one injected bad-but-plausible marker
    value (mimicking the real `240_25.mp4` frame 368 case) and silently
    returned a fitted omega ~2.5x the true value with the wrong sign --
    because a value landing near the +-180 deg branch cut relative to the
    true trend can flip which 360 deg branch *sequential* unwrap locks onto
    for every sample after it (it always branches relative to the previous
    raw sample, which after a flip is itself already wrong), so every later
    point's residual looks uniformly "fine" against the now-shifted trend
    instead of standing out as an outlier.

    Fix: choose each sample's branch relative to a robust linear
    *prediction*, refined over a few rounds, not relative to the previous
    raw sample -- seeded from an unwrap-free slope estimate
    (_robust_omega_seed) so the seed can't inherit the same failure mode.

    Returns (theta_unwrapped_rad, slope_rad_per_frame, intercept_rad,
    inlier_mask, residual_std_rad), all aligned to the input arrays
    (NaN/False at rows with no marker detection, i.e. non-finite
    theta_wrapped). residual_std_rad is the final fit's inlier residual
    std -- see _sigma_clip_linear_fit for why this matters more than the
    inlier/outlier counts alone.
    """
    valid = np.isfinite(theta_wrapped)
    out_theta = np.full(theta_wrapped.shape, np.nan, dtype=float)
    inlier_mask = np.zeros(theta_wrapped.shape, dtype=bool)
    if valid.sum() < min_points:
        return out_theta, np.nan, np.nan, inlier_mask, np.nan

    f = frame[valid]
    t = theta_wrapped[valid]

    slope = _robust_omega_seed(f, t)
    if not np.isfinite(slope):
        return out_theta, np.nan, np.nan, inlier_mask, np.nan
    intercept = t[0] - slope * f[0]  # anchor to the first valid sample

    residual_std = np.nan
    for _ in range(refine_rounds):
        unwrapped = t + 2 * np.pi * np.round((slope * f + intercept - t) / (2 * np.pi))
        new_slope, new_intercept, mask, residual_std = _sigma_clip_linear_fit(
            f, unwrapped, n_sigma=n_sigma, max_iters=max_iters, min_points=min_points
        )
        if not np.isfinite(new_slope):
            break
        slope, intercept = new_slope, new_intercept

    out_theta[valid] = unwrapped
    inlier_mask[valid] = mask
    return out_theta, slope, intercept, inlier_mask, residual_std


def fit_rotation_segments(dfm: pd.DataFrame, collision_frame: int,
                           n_sigma: float = 2.5, max_iters: int = 10,
                           min_points: int = 4) -> pd.DataFrame:
    """
    Per-disk angular-velocity fit, segmented at the collision frame and never
    fit across it (contact torque means omega isn't expected constant there
    -- see CLAUDE.md Rotation plan step 1). Within each segment, robustly
    unwraps and fits theta vs. frame (step 2) via _robust_unwrap_and_fit,
    which both estimates omega and flags which existing marker detections
    are trend-consistent vs. likely-false.

    Returns dfm with these columns added (row-aligned):
        theta_unwrapped_deg     : branch-robust unwrap (see
                                   _robust_unwrap_and_fit), NaN where no
                                   marker was detected that frame
        rotation_segment        : "before" / "after" / "collision" (frame ==
                                   collision_frame is excluded from fitting)
        theta_trend_consistent  : True/False for rows with a marker
                                   detection (inlier/outlier of that
                                   segment's fit); NaN for rows with no
                                   marker detection at all (nothing to judge)
        omega_fit_deg_per_frame : that row's segment's fitted slope
                                   (same value repeated across the segment),
                                   NaN if the segment couldn't be fit
        theta_fit_intercept_deg : that row's segment's fitted y-intercept
                                   (theta_deg at frame=0, same convention as
                                   omega_fit_deg_per_frame -- predicted
                                   theta at any frame f is
                                   omega_fit_deg_per_frame*f +
                                   theta_fit_intercept_deg), same
                                   broadcast/NaN behavior as the slope.
                                   Used by detector.fill_rotation_gaps
                                   (Rotation plan steps 3-5) to predict
                                   where a missing/rejected marker should
                                   be; not needed for the fit/outlier-flag
                                   use case alone.
        omega_fit_residual_std_deg : the fitted trend's own inlier residual
                                   std (deg) -- **do not treat "0 outliers"
                                   alone as "this fit is trustworthy."**
                                   Sigma-clipping only rejects points that
                                   stand out relative to the fit's *own*
                                   noise floor; if much of a segment's data
                                   is genuinely poor, that floor inflates
                                   and nothing looks like an outlier
                                   anymore. Measured directly on real
                                   footage (`240_25.mp4` disk 1, a segment
                                   that reported 68 inliers/0 outliers and
                                   omega in line with the ~1 deg/frame
                                   expectation): residual std was ~79 deg,
                                   and refitting after randomly holding out
                                   35% of those "inliers" swung the fitted
                                   omega anywhere from -1.0 to +1.86
                                   deg/frame across different holdout draws
                                   -- a fit that looks clean by inlier count
                                   alone but is not actually precise enough
                                   to extrapolate from. Gate on this before
                                   trusting a fit for anything beyond a
                                   rough sign/order-of-magnitude read; see
                                   detector.py's recovery-confidence gate.
    """
    out = dfm.copy()
    dx = (out["mx"] - out["cx"]).to_numpy()
    dy = (out["my"] - out["cy"]).to_numpy()
    theta_wrapped = np.arctan2(dy, dx)  # NaN where marker missing

    frame = out["frame"].to_numpy(dtype=float)
    seg = np.where(frame < collision_frame, "before",
          np.where(frame > collision_frame, "after", "collision"))
    out["rotation_segment"] = seg

    theta_unwrapped_deg = np.full(len(out), np.nan, dtype=float)
    trend_consistent = np.full(len(out), np.nan, dtype=object)
    omega_fit = np.full(len(out), np.nan, dtype=float)
    intercept_fit = np.full(len(out), np.nan, dtype=float)
    residual_std_fit = np.full(len(out), np.nan, dtype=float)

    for label in ("before", "after"):
        seg_idx = np.flatnonzero(seg == label)
        if seg_idx.size == 0:
            continue
        f = frame[seg_idx]
        tw = theta_wrapped[seg_idx]
        unwrapped_rad, slope_rad, intercept_rad, inlier, residual_std_rad = _robust_unwrap_and_fit(
            f, tw, n_sigma=n_sigma, max_iters=max_iters, min_points=min_points
        )
        theta_unwrapped_deg[seg_idx] = np.degrees(unwrapped_rad)
        has_marker = np.isfinite(tw)
        trend_consistent[seg_idx] = np.where(has_marker, inlier, np.nan)
        omega_fit[seg_idx] = np.degrees(slope_rad) if np.isfinite(slope_rad) else np.nan
        intercept_fit[seg_idx] = np.degrees(intercept_rad) if np.isfinite(intercept_rad) else np.nan
        residual_std_fit[seg_idx] = np.degrees(residual_std_rad) if np.isfinite(residual_std_rad) else np.nan

    out["theta_unwrapped_deg"] = theta_unwrapped_deg
    out["theta_trend_consistent"] = trend_consistent
    out["omega_fit_deg_per_frame"] = omega_fit
    out["theta_fit_intercept_deg"] = intercept_fit
    out["omega_fit_residual_std_deg"] = residual_std_fit
    return out


def _rotation_segment_summary(out: pd.DataFrame) -> dict:
    """Per-segment omega + inlier/outlier/missing counts from fit_rotation_segments' output."""
    summary = {}
    for label in ("before", "after"):
        seg = out.loc[out["rotation_segment"] == label]
        tc = seg["theta_trend_consistent"]
        omega_vals = seg["omega_fit_deg_per_frame"].dropna()
        summary[label] = {
            "omega_deg_per_frame": float(omega_vals.iloc[0]) if not omega_vals.empty else np.nan,
            "n_inliers": int((tc == True).sum()),
            "n_outliers": int((tc == False).sum()),
            "n_missing": int(tc.isna().sum()),
        }
    return summary


def fit_rotation(df0_raw: pd.DataFrame, df1_raw: pd.DataFrame,
                  n_sigma: float = 2.5, max_iters: int = 10, min_points: int = 4):
    """
    Full entry point: raw per-disk detection rows (as read from the exported
    CSV and split by disk_id) -> per-disk row-level rotation-fit columns
    (see fit_rotation_segments) plus a compact summary, sharing one
    collision frame between both disks.

    Returns (out0, out1, summary) where summary = {
        "collision_frame": int,
        0: {"before": {...}, "after": {...}},
        1: {"before": {...}, "after": {...}},
    } -- see _rotation_segment_summary for the per-segment dict shape.
    """
    df0m = _add_meter_cols(_ensure_sorted(df0_raw))
    df1m = _add_meter_cols(_ensure_sorted(df1_raw))
    cf = _find_collision_frame(df0m, df1m)
    out0 = fit_rotation_segments(df0m, cf, n_sigma, max_iters, min_points)
    out1 = fit_rotation_segments(df1m, cf, n_sigma, max_iters, min_points)
    summary = {
        "collision_frame": cf,
        0: _rotation_segment_summary(out0),
        1: _rotation_segment_summary(out1),
    }
    return out0, out1, summary


def _find_collision_frame(df0m: pd.DataFrame, df1m: pd.DataFrame) -> int:
    """
    Forced-unique collision frame = frame of minimal center-to-center distance.
    """
    m = pd.merge(df0m[["frame","cx","cy"]], df1m[["frame","cx","cy"]],
                 on="frame", suffixes=("_0","_1"))
    dx = m["cx_1"] - m["cx_0"]
    dy = m["cy_1"] - m["cy_0"]
    return int(m.loc[np.hypot(dx, dy).idxmin(), "frame"])

def _safe_vxvy_mean(df: pd.DataFrame, mask: pd.Series) -> np.ndarray:
    """
    Mean of ["vx","vy"] over the masked rows -> NaN for a column with no
    non-NaN values in the selection (empty selection, or the lone row is a
    disk's first sample, whose vx/vy/omega are always NaN — they come from
    a frame-to-frame diff() with nothing before them). That's already the
    correct/expected result; the only thing suppressed here is numpy's
    "RuntimeWarning: Mean of empty slice" that pandas triggers getting there,
    which happens routinely with sparse/short tracking data and isn't a bug.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning)
        return df.loc[mask, ["vx", "vy"]].mean().to_numpy()


def _safe_median(series: pd.Series) -> float:
    """Same empty-slice/all-NaN guard as _safe_vxvy_mean, for the .median() calls below."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning)
        return float(series.median())


# Metrics
def _compute_metrics(df0m: pd.DataFrame, df1m: pd.DataFrame, masses: tuple, radius: tuple, fps: float):
    """
    Returns a dict with:
        - collision_frame
        - restitution_e (full-data means, along line-of-centers)
        - momentum_error_rel (full-data means)
        - energy_drop_rel_COM (medians with COM de-jitter, includes rotation)
    """
    # Collision frame
    cf = _find_collision_frame(df0m, df1m)

    before0 = df0m["frame"] < cf
    after0  = df0m["frame"] > cf
    before1 = df1m["frame"] < cf
    after1  = df1m["frame"] > cf

    # ---- Coefficient of restitution e (means, full data; line of centers) ----
    v0b = _safe_vxvy_mean(df0m, before0)
    v0a = _safe_vxvy_mean(df0m, after0)
    v1b = _safe_vxvy_mean(df1m, before1)
    v1a = _safe_vxvy_mean(df1m, after1)

    # Line-of-centers at collision (meters)
    p0c = df0m.loc[df0m["frame"] == cf, ["cx","cy"]]
    p1c = df1m.loc[df1m["frame"] == cf, ["cx","cy"]]
    if p0c.empty or p1c.empty:  # fallback if exact frame missing
        p0c = df0m.iloc[[(df0m["frame"] - cf).abs().idxmin()]][["cx","cy"]]
        p1c = df1m.iloc[[(df1m["frame"] - cf).abs().idxmin()]][["cx","cy"]]
    nvec = (p1c.values[0] - p0c.values[0]).astype(float)
    n = nvec / (np.linalg.norm(nvec) + 1e-12)

    vrel_b = np.array([v1b[0] - v0b[0], v1b[1] - v0b[1]])
    vrel_a = np.array([v1a[0] - v0a[0], v1a[1] - v0a[1]])
    v_n_before = -float(np.dot(vrel_b, n))   # approach speed (>0)
    v_n_after  =  float(np.dot(vrel_a, n))   # separation speed (>=0)
    e = float(v_n_after / v_n_before) if (np.isfinite(v_n_before) and v_n_before > 1e-12) else np.nan

    # ---- Momentum error (relative; full-data means) ----
    RADIUS_M = (radius[0] + radius[1]) / 2
    MASS = {0: masses[0], 1: masses[1]}
    p_before = np.array([MASS[0]*v0b[0] + MASS[1]*v1b[0],
                         MASS[0]*v0b[1] + MASS[1]*v1b[1]])
    p_after  = np.array([MASS[0]*v0a[0] + MASS[1]*v1a[0],
                         MASS[0]*v0a[1] + MASS[1]*v1a[1]])
    p_err = float(np.linalg.norm(p_after - p_before) / (np.linalg.norm(p_before) + 1e-12))

    # ---- Energy drop (relative, COM frame; medians) ----
    INERTIA = {i: 0.5 * MASS[i] * (RADIUS_M**2) for i in (0, 1)}
    Mtot = MASS[0] + MASS[1]

    m = pd.merge(
        df0m[["frame", "vx", "vy"]],
        df1m[["frame", "vx", "vy"]],
        on="frame", how="inner", suffixes=("0", "1"),
    )
    mb = m["frame"] < cf
    ma = m["frame"] > cf

    Vcm_x = (MASS[0]*m["vx0"] + MASS[1]*m["vx1"]) / Mtot
    Vcm_y = (MASS[0]*m["vy0"] + MASS[1]*m["vy1"]) / Mtot

    v0x_b = _safe_median(m.loc[mb, "vx0"] - Vcm_x.loc[mb])
    v0y_b = _safe_median(m.loc[mb, "vy0"] - Vcm_y.loc[mb])
    v1x_b = _safe_median(m.loc[mb, "vx1"] - Vcm_x.loc[mb])
    v1y_b = _safe_median(m.loc[mb, "vy1"] - Vcm_y.loc[mb])

    v0x_a = _safe_median(m.loc[ma, "vx0"] - Vcm_x.loc[ma])
    v0y_a = _safe_median(m.loc[ma, "vy0"] - Vcm_y.loc[ma])
    v1x_a = _safe_median(m.loc[ma, "vx1"] - Vcm_x.loc[ma])
    v1y_a = _safe_median(m.loc[ma, "vy1"] - Vcm_y.loc[ma])

    # Prefer the RANSAC/sigma-clip segment fit (fit_rotation_segments) over
    # the raw per-frame omega_deg_s median: the median is robust to gaps but
    # not to a wrong-but-plausible single-frame value (the known 240_25.mp4
    # frame 368 false positive is exactly this — a confidently-wrong value,
    # not a gap), which the trend fit rejects structurally instead. Falls
    # back to the raw median when the fit can't run at all (fewer than
    # fit_rotation_segments' min_points marker detections in that segment) so
    # sparse segments don't lose energy-metric coverage they used to have.
    out0 = fit_rotation_segments(df0m, cf)
    out1 = fit_rotation_segments(df1m, cf)

    def _segment_omega_deg_s(fitted_out, raw_df, raw_mask, label):
        fitted = fitted_out.loc[fitted_out["rotation_segment"] == label, "omega_fit_deg_per_frame"].dropna()
        if not fitted.empty:
            return float(fitted.iloc[0]) * fps  # deg/frame -> deg/s
        return _safe_median(raw_df.loc[raw_mask, "omega_deg_s"])

    o0b = _segment_omega_deg_s(out0, df0m, before0, "before")
    o0a = _segment_omega_deg_s(out0, df0m, after0, "after")
    o1b = _segment_omega_deg_s(out1, df1m, before1, "before")
    o1a = _segment_omega_deg_s(out1, df1m, after1, "after")

    Kb_com = 0.5*MASS[0]*(v0x_b**2 + v0y_b**2) + 0.5*MASS[1]*(v1x_b**2 + v1y_b**2)
    Ka_com = 0.5*MASS[0]*(v0x_a**2 + v0y_a**2) + 0.5*MASS[1]*(v1x_a**2 + v1y_a**2)

    def _K_rot(I, omega_deg):
        w = math.radians(omega_deg) if np.isfinite(omega_deg) else np.nan
        return 0.5*I*(w**2) if np.isfinite(w) else np.nan

    Kr0b = _K_rot(INERTIA[0], o0b)
    Kr1b = _K_rot(INERTIA[1], o1b)
    Kr0a = _K_rot(INERTIA[0], o0a)
    Kr1a = _K_rot(INERTIA[1], o1a)

    Kb_total_com = Kb_com + Kr0b + Kr1b
    Ka_total_com = Ka_com + Kr0a + Kr1a
    K_drop_COM = float((Kb_total_com - Ka_total_com) / (Kb_total_com if np.isfinite(Kb_total_com) and Kb_total_com > 0 else 1e-12))

    return {
        "collision_frame": cf,
        "restitution_e": e,
        "momentum_error_rel": p_err,
        "energy_drop_rel_COM": K_drop_COM,
    }

# --------------------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------------------
def visualize_trajectories(
    csv_path: str,
    output_image_path: str,
    fps: float = 30.0,
    show_equal_aspect: bool = True,
    show_title: bool = True,
) -> int:
    csvp = Path(csv_path)
    if not csvp.exists():
        raise FileNotFoundError(csvp.resolve())

    df = pd.read_csv(csvp)
    missing = [c for c in REQ_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")

    df0 = _ensure_sorted(df[df["disk_id"] == 0].copy())
    df1 = _ensure_sorted(df[df["disk_id"] == 1].copy())
    df0m = _add_meter_cols(df0)
    df1m = _add_meter_cols(df1)

    cf = _find_collision_frame(df0m, df1m)

    p0 = df0m.loc[df0m["frame"] == cf, ["cx", "cy"]].head(1)
    p1 = df1m.loc[df1m["frame"] == cf, ["cx", "cy"]].head(1)

    # Creating a large canvas (12x8 inches @ 150 DPI = 1800x1200 real screen pixels)
    fig, ax = plt.subplots(figsize=(12, 8), dpi=150)

    ax.plot(df0m["cx"], df0m["cy"], label="Disk 0 trajectory", linewidth=2)
    ax.plot(df1m["cx"], df1m["cy"], label="Disk 1 trajectory", linewidth=2)

    if not p0.empty:
        ax.scatter(p0["cx"], p0["cy"], s=90, marker="o", edgecolors="k", zorder=5,
                   label=f"collision @ disk 0 (f={cf})")
    if not p1.empty:
        ax.scatter(p1["cx"], p1["cy"], s=90, marker="s", edgecolors="k", zorder=5,
                   label=f"collision @ disk 1 (f={cf})")

    ax.set_xlabel("x [m]", fontsize=11)
    ax.set_ylabel("y [m]", fontsize=11)
    
    if show_equal_aspect:
        ax.set_aspect("equal", adjustable="datalim")
        
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=10)
    
    if show_title:
        ax.set_title("Puck trajectories with collision frame highlighted", fontsize=12, pad=10)

    outp = Path(output_image_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    
    fig.tight_layout()
    fig.savefig(outp, dpi=300)
    
    return cf

def build_student_excel(
    csv_path: str,
    output_xlsx_path: str,
    masses: tuple,
    radius: tuple,
    fps: float = 30.0,
    include_metrics: bool = False,
) -> int:
    """
    Build an Excel similar to your current one, but with:
        - time_s (frame/FPS)
        - disk_id
        - x_m, y_m (meters, centers)
        - theta_deg (unwrapped; marker-to-center angle)

    If include_metrics=True, adds a "Results" sheet with restitution, momentum error, COM energy drop.
    Returns the collision frame (int).
    """
    csvp = Path(csv_path)
    if not csvp.exists():
        raise FileNotFoundError(csvp.resolve())
    df = pd.read_csv(csvp)
    missing = [c for c in REQ_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")

    df0_raw = _ensure_sorted(df[df["disk_id"]==0].copy())
    df1_raw = _ensure_sorted(df[df["disk_id"]==1].copy())
    df0m = _add_meter_cols(df0_raw)
    df1m = _add_meter_cols(df1_raw)

    th0 = _unwrap_angle(df0m)
    th1 = _unwrap_angle(df1m)
    df0m["theta_deg"] = np.degrees(th0)
    df1m["theta_deg"] = np.degrees(th1)
    df0m["time_s"] = df0m["frame"] / float(fps)
    df1m["time_s"] = df1m["frame"] / float(fps)

    cf = _find_collision_frame(df0m, df1m)

    cols_student = ["time_s","disk_id","frame","cx","cy","theta_deg"]
    tbl0 = df0m.assign(disk_id=0)[cols_student].rename(columns={"cx":"x_m","cy":"y_m"})
    tbl1 = df1m.assign(disk_id=1)[cols_student].rename(columns={"cx":"x_m","cy":"y_m"})
    students_tbl = pd.concat([tbl0, tbl1], ignore_index=True).sort_values(["time_s","disk_id"])

    results_df = None
    if include_metrics:
        df0m_vel = _compute_vels(df0m, fps=fps)
        df1m_vel = _compute_vels(df1m, fps=fps)
        metrics = _compute_metrics(df0m_vel, df1m_vel, masses, radius, fps=fps)
        results_df = pd.DataFrame(
            [
                ("Collision frame (excluded)", metrics["collision_frame"]),
                ("e (restitution, full-data means)",
                 f'{metrics["restitution_e"]:.6g}' if np.isfinite(metrics["restitution_e"]) else str(metrics["restitution_e"])),
                ("Momentum error (rel, full-data means)",
                 f'{metrics["momentum_error_rel"]:.6g}' if np.isfinite(metrics["momentum_error_rel"]) else str(metrics["momentum_error_rel"])),
                ("Energy drop (rel, COM frame)",
                 f'{metrics["energy_drop_rel_COM"]:.6g}' if np.isfinite(metrics["energy_drop_rel_COM"]) else str(metrics["energy_drop_rel_COM"])),
            ],
            columns=["Quantity","Value"]
        )

    outp = Path(output_xlsx_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(outp, engine="openpyxl") as writer:
        students_tbl.to_excel(writer, index=False, sheet_name="Raw_Data")
        if include_metrics and results_df is not None:
            results_df.to_excel(writer, index=False, sheet_name="Results")

    return cf
