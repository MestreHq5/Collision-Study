# compute_velocities_simple.py
# Minimal: manual tweaks only, no smoothing, no bells & whistles.

import math
import numpy as np
import pandas as pd

# ==== TWEAK THESE CONSTANTS ====
TRACKS_CSV         = "C:/Users/gonca/Desktop/Collisions DEM/Collision-Study/disk_tracks.csv"        # input tracks
COLLISIONS_CSV     = "C:/Users/gonca/Desktop/Collisions DEM/Collision-Study/Tests/collisions_simple.csv"  # must have a column 'frame'
FPS                = 60.0                    # frames per second
WINDOW_FRAMES      = 3                       # frames before/after collision to summarize
MIN_MARK_RADIUS_MM = 2.0                      # ignore angular velocity if marker radius < this
OUTPUT_CSV         = "velocities_summary.csv"
# ===============================

def load_data(tracks_csv, collisions_csv):
    df = pd.read_csv(tracks_csv, na_values=["", "None"]).sort_values(["disk_id","frame"])
    needed = {"frame","disk_id","cx_mm","cy_mm","mx_mm","my_mm"}
    miss = needed - set(df.columns)
    if miss:
        raise ValueError(f"{tracks_csv} missing columns: {miss}")
    df["frame"] = df["frame"].astype(int)
    df["disk_id"] = df["disk_id"].astype(int)

    cdf = pd.read_csv(collisions_csv)
    if "frame" not in cdf.columns:
        raise ValueError(f"{collisions_csv} must contain column 'frame'")
    collisions = sorted(set(cdf["frame"].dropna().astype(int).tolist()))
    if not collisions:
        raise ValueError("No collision frames found.")
    return df, collisions

def linear_velocity(df_disk, fps):
    dt = 1.0 / float(fps)
    g = df_disk.sort_values("frame").copy()
    g["vx"] = g["cx_mm"].diff() / dt
    g["vy"] = g["cy_mm"].diff() / dt
    g["speed"] = np.hypot(g["vx"], g["vy"])
    return g.set_index("frame")[["speed"]]

def angular_velocity(df_disk, fps, min_r_mm):
    dt = 1.0 / float(fps)
    g = df_disk.sort_values("frame").copy()
    dx = g["mx_mm"] - g["cx_mm"]
    dy = g["my_mm"] - g["cy_mm"]
    r  = np.hypot(dx, dy)
    angle = np.arctan2(dy, dx)
    angle[g["mx_mm"].isna() | g["my_mm"].isna()] = np.nan
    a = angle.to_numpy(dtype=float)
    mask = ~np.isnan(a)
    uw = np.full_like(a, np.nan)
    if mask.any():
        uw[mask] = np.unwrap(a[mask])
    omega = pd.Series(uw).diff() / dt  # rad/s
    out = pd.DataFrame({"frame": g["frame"].values,
                        "omega_rad_s": omega.values,
                        "marker_r_mm": r.values}).set_index("frame")
    out.loc[out["marker_r_mm"] < float(min_r_mm), "omega_rad_s"] = np.nan
    return out[["omega_rad_s"]]

def median_before_after(series: pd.Series, f_center: int, f_min: int, f_max: int,
                        prev_fc: int | None, next_fc: int | None):
    """
    Median over a fixed, local window:
      Before: frames [f_center-3 .. f_center-1]
      After:  frames [f_center+1 .. f_center+3]
    Clamps to available frames and ignores NaNs.
    """
    if series.empty:
        return np.nan, np.nan

    W = 3  # or use WINDOW_FRAMES if you prefer the constant
    before_range = range(max(f_center - W, f_min), max(f_center, f_min))
    after_range  = range(min(f_center + 1, f_max + 1), min(f_center + W + 1, f_max + 1))

    before_vals = series.loc[series.index.intersection(before_range)].to_numpy()
    after_vals  = series.loc[series.index.intersection(after_range)].to_numpy()

    mb = float(np.nanmedian(before_vals)) if before_vals.size else np.nan
    ma = float(np.nanmedian(after_vals))  if after_vals.size  else np.nan
    return mb, ma

def restitution_coef_proper(df_tracks, df_out, collision_frame, window=3):
    """
    Compute e from signed normal components around 'collision_frame'.
    Uses median velocities over [fc-3..fc-1] and [fc+1..fc+3] by default.
    """
    # 1) build per-frame velocity vectors for each disk
    dt = 1.0 / FPS
    trk = df_tracks.sort_values(["disk_id","frame"]).copy()
    trk["vx"] = trk.groupby("disk_id")["cx_mm"].diff() / dt
    trk["vy"] = trk.groupby("disk_id")["cy_mm"].diff() / dt

    # 2) unit normal n from disk 0 → disk 1 at the collision frame (or nearest available)
    # use center positions at fc (fallback to closest existing frame)
    p0 = trk[trk["disk_id"]==0].set_index("frame")[["cx_mm","cy_mm"]]
    p1 = trk[trk["disk_id"]==1].set_index("frame")[["cx_mm","cy_mm"]]

    if collision_frame not in p0.index or collision_frame not in p1.index:
        # pick nearest available frame
        f0 = p0.index.to_numpy()
        f1 = p1.index.to_numpy()
        # nearest frames to fc that are common to both
        common = np.intersect1d(f0, f1)
        if common.size == 0:
            return np.nan
        fc_use = int(common[np.argmin(np.abs(common - collision_frame))])
    else:
        fc_use = collision_frame

    r01 = (p1.loc[fc_use] - p0.loc[fc_use]).to_numpy()
    norm = np.linalg.norm(r01)
    if not np.isfinite(norm) or norm < 1e-6:
        return np.nan
    n = r01 / norm

    # 3) gather velocity medians in a small window before/after
    def med_v(did, start_f, end_f):
        g = trk[trk["disk_id"]==did]
        win = g[(g["frame"]>=start_f) & (g["frame"]<=end_f)][["vx","vy"]]
        if len(win)==0:
            return np.array([np.nan, np.nan])
        return np.nanmedian(win.to_numpy(), axis=0)

    W = window
    v0b = med_v(0, collision_frame - W, collision_frame - 1)
    v1b = med_v(1, collision_frame - W, collision_frame - 1)
    v0a = med_v(0, collision_frame + 1, collision_frame + W)
    v1a = med_v(1, collision_frame + 1, collision_frame + W)

    # 4) relative normal speeds
    def dotn(v): 
        return float(np.dot(v, n)) if np.all(np.isfinite(v)) else np.nan

    u_n = dotn(v1b - v0b)  # approach speed along n (should be +)
    v_n = dotn(v1a - v0a)  # separation speed along n (should be -)

    if not np.isfinite(u_n) or abs(u_n) < 1e-6:
        return np.nan
    # Ensure positive 'approach' sign (flip n if needed)
    if u_n < 0:
        n[:] = -n
        u_n = -u_n
        v_n = -v_n

    e = -v_n / u_n
    return float(e)


def check_linear_moment(df_out):
    
    # Separation Speed Value
    green_disk_sep = df_out.loc[
    (df_out["disk_id"] == 0),
    "linear_after_mm_s"
    ].values[0]
    
    blue_disk_sep = df_out.loc[
    (df_out["disk_id"] == 1),
    "linear_after_mm_s"
    ].values[0]
    
    green_disk_apr = df_out.loc[
    (df_out["disk_id"] == 0),
    "linear_before_mm_s"
    ].values[0]
    
    blue_disk_apr = df_out.loc[
    (df_out["disk_id"] == 1),
    "linear_before_mm_s"
    ].values[0]
    
    linear_before = green_disk_apr + blue_disk_apr
    linear_after = green_disk_sep + blue_disk_sep
    
    deviation = (linear_after - linear_before) / linear_before
    
    return deviation


def main():
    df, collisions = load_data(TRACKS_CSV, COLLISIONS_CSV)
    f_min, f_max = int(df["frame"].min()), int(df["frame"].max())

    coll_sorted = sorted(collisions)
    neighbors = {fc: ((coll_sorted[i-1] if i>0 else None),
                      (coll_sorted[i+1] if i+1<len(coll_sorted) else None))
                 for i, fc in enumerate(coll_sorted)}

    rows = []
    for disk_id, df_disk in df.groupby("disk_id"):
        lin = linear_velocity(df_disk, FPS)
        ang = angular_velocity(df_disk, FPS, MIN_MARK_RADIUS_MM)

        for fc in coll_sorted:
            prev_fc, next_fc = neighbors[fc]
            lin_b, lin_a = median_before_after(lin["speed"], fc, f_min, f_max, prev_fc, next_fc)
            ang_b, ang_a = median_before_after(ang["omega_rad_s"], fc, f_min, f_max, prev_fc, next_fc)

            rows.append({
                "collision_frame": int(fc),
                "disk_id": int(disk_id),
                "linear_before_mm_s": lin_b,
                "linear_after_mm_s":  lin_a,
                "angular_before_rad_s": ang_b,
                "angular_after_rad_s":  ang_a,
            })

    

    out = pd.DataFrame(rows).sort_values(["collision_frame","disk_id"])
    out.to_csv(OUTPUT_CSV, index=False)
    with pd.option_context("display.max_columns", None, "display.width", 160):
        print(out.to_string(index=False))
    print(f"\nSaved -> {OUTPUT_CSV}")
    
    # Check the value of the Restitution Coeficient
    # read the tracks once here (same CSV you pass at top)
    df_tracks = pd.read_csv(TRACKS_CSV, na_values=["","None"])

    # pick the (single) collision frame you want, or loop over out["collision_frame"].unique()
    fc = int(out["collision_frame"].iloc[0])
    e = restitution_coef_proper(df_tracks, out[out["collision_frame"]==fc], fc, window=3)
    print(f"Estimated Restitution (proper, normal-based) at frame {fc}: {e:.3f}")

    
    # Check Linear Moment Conservation
    deviation = check_linear_moment(out)
    print(f"Estimated Linear Moment Deviation: {deviation}")
    
    # Check Energy Drop
    
    

if __name__ == "__main__":
    main()