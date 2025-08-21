# compute_velocities_simple.py
# Minimal: manual tweaks only, no smoothing, no bells & whistles.

import math
import numpy as np
import pandas as pd

# ==== TWEAK THESE CONSTANTS ====
TRACKS_CSV         = "C:/Users/gonca/Desktop/Collisions DEM/Collision-Study/disk_tracks.csv"        # input tracks
COLLISIONS_CSV     = "C:/Users/gonca/Desktop/Collisions DEM/Collision-Study/Tests/collisions_simple.csv"  # must have a column 'frame'
FPS                = 60.0                    # frames per second
WINDOW_FRAMES      = 15                       # frames before/after collision to summarize
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
    """Medians over all available frames before/after, bounded by prev/next collisions."""
    if series.empty:
        return np.nan, np.nan
    start_before = (prev_fc + 1) if prev_fc is not None else f_min
    end_before   = f_center - 1
    start_after  = f_center + 1
    end_after    = (next_fc - 1) if next_fc is not None else f_max

    if end_before >= start_before:
        before_vals = series.loc[series.index.intersection(range(start_before, end_before + 1))].to_numpy()
        mb = float(np.nanmedian(before_vals)) if before_vals.size else np.nan
    else:
        mb = np.nan

    if end_after >= start_after:
        after_vals = series.loc[series.index.intersection(range(start_after, end_after + 1))].to_numpy()
        ma = float(np.nanmedian(after_vals)) if after_vals.size else np.nan
    else:
        ma = np.nan

    return mb, ma

def restitution_coef(df_out):
    
    # Separation Speed Value
    green_disk_sep = df_out.loc[
    (df_out["disk_id"] == 0),
    "linear_after_mm_s"
    ].values[0]
    
    blue_disk_sep = df_out.loc[
    (df_out["disk_id"] == 1),
    "linear_after_mm_s"
    ].values[0]
    
    sep_speed = green_disk_sep - blue_disk_sep
    
    green_disk_apr = df_out.loc[
    (df_out["disk_id"] == 0),
    "linear_before_mm_s"
    ].values[0]
    
    blue_disk_apr = df_out.loc[
    (df_out["disk_id"] == 1),
    "linear_before_mm_s"
    ].values[0]
    
    apr_speed = green_disk_apr - blue_disk_apr
    
    
    coef = sep_speed / apr_speed
    
    return coef

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
    linear_after = green_disk_sep + green_disk_sep
    
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
    rest_coef = restitution_coef(out)
    print(f"Estimated Restitution Coeficient: {rest_coef}")
    
    # Check Linear Moment Conservation
    deviation = check_linear_moment(out)
    print(f"Estimated Linear Moment Deviation: {deviation}")
    
    # Check Energy Drop
    
    

if __name__ == "__main__":
    main()