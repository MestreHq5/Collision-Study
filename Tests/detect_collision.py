import math
import numpy as np
import pandas as pd

# ==== EDIT THESE CONSTANTS MANUALLY ====
CSV_PATH              = "C:/Users/gonca/Desktop/Collisions DEM/Collision-Study/disk_tracks.csv"
OUTPUT_PATH           = "collisions_simple.csv"

FPS                   = 60.0      # frames per second
DIAMETER_MM           = 80.0      # puck diameter in mm
PROX_TOL_MM           = 10.0      # extra slack for proximity test

ANGLE_DEG             = 10.0      # heading change threshold (degrees)
SPEED_JUMP_MM_S       = 100.0     # speed jump threshold (mm/s)
MIN_SPEED_FOR_ANGLE   = 20.0      # only evaluate heading change if both speeds >= this
# ======================================


def load_tracks(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, na_values=["", "None"])
    # keep only rows with valid centers
    df = df.dropna(subset=["cx_mm", "cy_mm"])
    # ensure types & order
    df["frame"] = df["frame"].astype(int)
    df["disk_id"] = df["disk_id"].astype(int)
    df = df.sort_values(["disk_id", "frame"]).reset_index(drop=True)
    return df


def compute_kinematics(df: pd.DataFrame, fps: float) -> pd.DataFrame:
    """Adds vx, vy, speed, heading, d_heading, d_speed_abs per puck & frame."""
    dt = 1.0 / fps
    # velocities (simple first difference)
    df[["vx", "vy"]] = (
        df.groupby("disk_id")[["cx_mm", "cy_mm"]].diff() / dt
    )
    df["speed"]   = np.hypot(df["vx"], df["vy"])
    df["heading"] = np.arctan2(df["vy"], df["vx"])

    # previous values
    df["heading_prev"] = df.groupby("disk_id")["heading"].shift(1)
    df["speed_prev"]   = df.groupby("disk_id")["speed"].shift(1)

    # angle change: only when both speeds are above a small floor
    def ang_diff(a, b):
        if np.isnan(a) or np.isnan(b):
            return np.nan
        d = (a - b + math.pi) % (2 * math.pi) - math.pi
        return abs(d)

    def safe_ang_change(row):
        if pd.isna(row["heading_prev"]):
            return np.nan
        if (row["speed"] < MIN_SPEED_FOR_ANGLE) or (row["speed_prev"] < MIN_SPEED_FOR_ANGLE):
            return np.nan
        return ang_diff(row["heading"], row["heading_prev"])

    df["d_heading"]   = df.apply(safe_ang_change, axis=1)          # radians
    df["d_speed_abs"] = (df["speed"] - df["speed_prev"]).abs()

    return df


def proximity_test(df: pd.DataFrame, diameter_mm: float, tol_mm: float) -> pd.Series:
    """
    Returns a boolean Series indexed by frame:
      True if distance between puck centers <= diameter + tol
    """
    wide = df.pivot_table(index="frame", columns="disk_id", values=["cx_mm", "cy_mm"])
    # Expect exactly two disks: 0 and 1
    if (0 not in wide["cx_mm"].columns) or (1 not in wide["cx_mm"].columns):
        # If a frame is missing a puck, test returns False for that frame
        prox = pd.Series(False, index=wide.index)
        return prox

    dx = wide["cx_mm"][0] - wide["cx_mm"][1]
    dy = wide["cy_mm"][0] - wide["cy_mm"][1]
    dist = np.hypot(dx, dy)

    thresh = diameter_mm + tol_mm
    prox_hit = (dist <= thresh)
    prox_hit.name = "prox_hit"
    return prox_hit


def velocity_change_test(df: pd.DataFrame,
                         angle_deg: float,
                         speed_jump_mm_s: float) -> pd.Series:
    """
    Returns a boolean Series indexed by frame:
      True if (for puck 0 OR puck 1) we see
         d_heading >= angle_deg  OR  d_speed_abs >= speed_jump_mm_s
    """
    thr_ang = math.radians(angle_deg)

    # pack per puck per frame signals, then combine by frame
    sig = (df.assign(
            ang_hit = df["d_heading"] >= thr_ang,
            spd_hit = df["d_speed_abs"] >= speed_jump_mm_s
          )
          .groupby(["frame", "disk_id"])[["ang_hit", "spd_hit"]]
          .max()
          .reset_index())

    by_frame = (sig.assign(hit = sig["ang_hit"] | sig["spd_hit"])
                  .groupby("frame")["hit"].any())
    by_frame.name = "dyn_hit"
    return by_frame


def main():
    df = load_tracks(CSV_PATH)
    df = compute_kinematics(df, FPS)

    prox = proximity_test(df, DIAMETER_MM, PROX_TOL_MM)
    dyn  = velocity_change_test(df, ANGLE_DEG, SPEED_JUMP_MM_S)

    # Align indices and take logical AND
    # Only frames present in both Series will be kept; reindex to union just in case
    idx = prox.index.union(dyn.index)
    prox = prox.reindex(idx, fill_value=False)
    dyn  = dyn.reindex(idx,  fill_value=False)

    both = (prox & dyn)
    collision_frames = both.index[both].astype(int)

    # Write result CSV
    out = pd.DataFrame({"frame": collision_frames})
    out.to_csv(OUTPUT_PATH, index=False)

    print(f"[OK] Possible collision frames ({len(out)}):")
    if len(out):
        print(out["frame"].to_list())
    print(f"[Saved] {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
