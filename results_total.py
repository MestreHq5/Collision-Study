#!/usr/bin/env python3
import math
from pathlib import Path
import numpy as np
import pandas as pd

# -----------------------------
# User constants (hard-coded)
# -----------------------------
CSV_PATH = "disk_tracks.csv"       # your CSV
OUTPUT_XLSX = "analysis_results.xlsx"
FPS = 54.89            # frames per second
RADIUS_M = 0.040                   # 40 mm -> 0.04 m
MASS = {0: 0.0118, 1: 0.0118}      # 11.8 g -> 0.0118 kg
INERTIA = {i: 0.5 * MASS[i] * (RADIUS_M**2) for i in (0, 1)}  # thin ring I = m R^2

REQ_COLS = ["frame","disk_id","cx_mm","cy_mm","mx_mm","my_mm","r_px","marker_color"]

# -----------------------------
# Minimal helpers
# -----------------------------
def ensure_sorted(df):
    return df.sort_values("frame").reset_index(drop=True)

def add_meter_cols(df_raw):
    df = df_raw.copy()
    df["cx"] = df["cx_mm"] / 1000.0
    df["cy"] = df["cy_mm"] / 1000.0
    df["mx"] = df["mx_mm"] / 1000.0
    df["my"] = df["my_mm"] / 1000.0
    return df

def compute_vels(df_m):
    out = df_m.copy()
    # Linear finite differences (m/s), aligned to later frame
    out["vx"] = out["cx"].diff() * FPS
    out["vy"] = out["cy"].diff() * FPS

    # Angular from marker vector
    theta = np.arctan2(out["my"] - out["cy"], out["mx"] - out["cx"]).to_numpy()
    theta_unwrapped = np.unwrap(theta)                 # radians
    dtheta = np.full(len(out), np.nan, dtype=float)    # length N
    dtheta[1:] = np.diff(theta_unwrapped)              # put N-1 diffs starting at index 1
    out["omega_deg_s"] = np.degrees(dtheta) * FPS      # deg/s, aligned to later frame

    return out


def find_collision_frame(df0, df1):
    m = pd.merge(df0[["frame","cx","cy"]], df1[["frame","cx","cy"]],
                 on="frame", suffixes=("_0","_1"))
    dx = m["cx_1"] - m["cx_0"]
    dy = m["cy_1"] - m["cy_0"]
    return int(m.loc[np.hypot(dx, dy).idxmin(), "frame"])

# -----------------------------
# Main
# -----------------------------
def main():
    # Read & validate
    csv_path = Path(CSV_PATH)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path.resolve())
    df = pd.read_csv(csv_path)
    missing = [c for c in REQ_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")

    # Split raw (keep mm/px for Excel)
    df0_raw = ensure_sorted(df[df["disk_id"] == 0].copy())
    df1_raw = ensure_sorted(df[df["disk_id"] == 1].copy())

    # Meter-based copies + velocities
    df0m = compute_vels(add_meter_cols(df0_raw))
    df1m = compute_vels(add_meter_cols(df1_raw))

    # Collision frame (exclude this frame from both sides)

    cf = find_collision_frame(df0m, df1m)
    before0 = df0m["frame"] < cf
    after0  = df0m["frame"] > cf
    before1 = df1m["frame"] < cf
    after1  = df1m["frame"] > cf

    # Mean velocities (full data, excl. cf) for restitution & momentum
    v0b = (df0m.loc[before0, ["vx","vy"]].mean().fillna(np.nan).values)
    v0a = (df0m.loc[after0,  ["vx","vy"]].mean().fillna(np.nan).values)
    v1b = (df1m.loc[before1, ["vx","vy"]].mean().fillna(np.nan).values)
    v1a = (df1m.loc[after1,  ["vx","vy"]].mean().fillna(np.nan).values)

    # Mean angular velocities (deg/s), excl. cf (for reporting)
    o0b = float(df0m.loc[before0, "omega_deg_s"].mean())
    o0a = float(df0m.loc[after0,  "omega_deg_s"].mean())
    o1b = float(df1m.loc[before1, "omega_deg_s"].mean())
    o1a = float(df1m.loc[after1,  "omega_deg_s"].mean())

    # Line-of-centers at collision (meters) for restitution direction
    p0c = df0m.loc[df0m["frame"] == cf, ["cx","cy"]]
    p1c = df1m.loc[df1m["frame"] == cf, ["cx","cy"]]
    if p0c.empty or p1c.empty:  # fallback to nearest
        p0c = df0m.iloc[[(df0m["frame"] - cf).abs().idxmin()]][["cx","cy"]]
        p1c = df1m.iloc[[(df1m["frame"] - cf).abs().idxmin()]][["cx","cy"]]
    nvec = (p1c.values[0] - p0c.values[0]).astype(float)
    n = nvec / (np.linalg.norm(nvec) + 1e-12)

    # Coefficient of restitution (full data means)
    vrel_b = np.array([v1b[0] - v0b[0], v1b[1] - v0b[1]])
    vrel_a = np.array([v1a[0] - v0a[0], v1a[1] - v0a[1]])
    v_n_before = -float(np.dot(vrel_b, n))   # approach speed (>0)
    v_n_after  =  float(np.dot(vrel_a, n))   # separation speed (>=0)
    e = float(v_n_after / v_n_before) if (np.isfinite(v_n_before) and v_n_before > 1e-12) else np.nan
    
    # Momentum conservation (full data means)
    p_before = np.array([MASS[0]*v0b[0] + MASS[1]*v1b[0],
                        MASS[0]*v0b[1] + MASS[1]*v1b[1]])
    p_after  = np.array([MASS[0]*v0a[0] + MASS[1]*v1a[0],
                        MASS[0]*v0a[1] + MASS[1]*v1a[1]])
    p_err = float(np.linalg.norm(p_after - p_before) / (np.linalg.norm(p_before) + 1e-12))

    # ----- Energy drop (use MEDIAN velocities over all frames, excl. cf) -----
    # Linear medians
    v0b_med = df0m.loc[before0, ["vx","vy"]].median().values.astype(float)
    v0a_med = df0m.loc[after0,  ["vx","vy"]].median().values.astype(float)
    v1b_med = df1m.loc[before1, ["vx","vy"]].median().values.astype(float)
    v1a_med = df1m.loc[after1,  ["vx","vy"]].median().values.astype(float)

    # Rotational medians (deg/s -> rad/s)
    o0b_med = float(df0m.loc[before0, "omega_deg_s"].median())
    o0a_med = float(df0m.loc[after0,  "omega_deg_s"].median())
    o1b_med = float(df1m.loc[before1, "omega_deg_s"].median())
    o1a_med = float(df1m.loc[after1,  "omega_deg_s"].median())

    def K_linear(m, vxy):  # from median components
        return 0.5*m*(vxy[0]**2 + vxy[1]**2) if np.all(np.isfinite(vxy)) else np.nan

    def K_rot(I, omega_deg):
        w = math.radians(omega_deg) if np.isfinite(omega_deg) else np.nan
        return 0.5*I*(w**2) if np.isfinite(w) else np.nan

    Kb = K_linear(MASS[0], v0b_med) + K_linear(MASS[1], v1b_med) \
    + K_rot(INERTIA[0], o0b_med) + K_rot(INERTIA[1], o1b_med)
    Ka = K_linear(MASS[0], v0a_med) + K_linear(MASS[1], v1a_med) \
    + K_rot(INERTIA[0], o0a_med) + K_rot(INERTIA[1], o1a_med)
    
    
    K_drop = float((Kb - Ka) / (Kb + 1e-12)) if (np.isfinite(Kb) and Kb > 0 and np.isfinite(Ka)) else np.nan

    # --- COM-dejittered energy (diagnostic) ---
    Mtot = MASS[0] + MASS[1]

    # Merge per-frame velocities for both disks
    m = pd.merge(
        df0m[["frame", "vx", "vy"]],
        df1m[["frame", "vx", "vy"]],
        on="frame",
        how="inner",
        suffixes=("0", "1"),
    )

    # Masks by frame (exclude collision frame)
    mb = m["frame"] < cf
    ma = m["frame"] > cf

    # Per-frame COM velocity
    Vcm_x = (MASS[0]*m["vx0"] + MASS[1]*m["vx1"]) / Mtot
    Vcm_y = (MASS[0]*m["vy0"] + MASS[1]*m["vy1"]) / Mtot

    # De-jittered component medians (before/after), per disk
    v0x_b = (m.loc[mb, "vx0"] - Vcm_x.loc[mb]).median()
    v0y_b = (m.loc[mb, "vy0"] - Vcm_y.loc[mb]).median()
    v1x_b = (m.loc[mb, "vx1"] - Vcm_x.loc[mb]).median()
    v1y_b = (m.loc[mb, "vy1"] - Vcm_y.loc[mb]).median()

    v0x_a = (m.loc[ma, "vx0"] - Vcm_x.loc[ma]).median()
    v0y_a = (m.loc[ma, "vy0"] - Vcm_y.loc[ma]).median()
    v1x_a = (m.loc[ma, "vx1"] - Vcm_x.loc[ma]).median()
    v1y_a = (m.loc[ma, "vy1"] - Vcm_y.loc[ma]).median()

    # Linear KE in COM frame (medians)
    Kb_com = 0.5*MASS[0]*(v0x_b**2 + v0y_b**2) + 0.5*MASS[1]*(v1x_b**2 + v1y_b**2)
    Ka_com = 0.5*MASS[0]*(v0x_a**2 + v0y_a**2) + 0.5*MASS[1]*(v1x_a**2 + v1y_a**2)

    # Rotational energies (reuse your earlier medians -> Kr0b, Kr1b, Kr0a, Kr1a)
    
    Kr0b = K_rot(INERTIA[0], o0b_med)
    Kr1b = K_rot(INERTIA[1], o1b_med)
    Kr0a = K_rot(INERTIA[0], o0a_med)
    Kr1a = K_rot(INERTIA[1], o1a_med)
    Kb_total_com = Kb_com + Kr0b + Kr1b
    Ka_total_com = Ka_com + Kr0a + Kr1a

    K_drop_COM = (Kb_total_com - Ka_total_com) / max(Kb_total_com, 1e-12)


    
    # -----------------------------
    # Write Excel: raw sheets + results
    # -----------------------------
    with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
        df0_raw.to_excel(writer, index=False, sheet_name="puck_0")
        df1_raw.to_excel(writer, index=False, sheet_name="puck_1")

        rows = [
            ("Collision frame (excluded)", cf),
            ("e (restitution, full-data means)", f"{e:.6g}"),
            ("Momentum error (rel, full-data means)", f"{p_err:.6g}"),
            ("Energy drop (rel, medians)", f"{K_drop:.6g}"),
            ("v0_before mean [m/s]", f"{v0b[0]:.6g}, {v0b[1]:.6g}"),
            ("v0_after  mean [m/s]", f"{v0a[0]:.6g}, {v0a[1]:.6g}"),
            ("v1_before mean [m/s]", f"{v1b[0]:.6g}, {v1b[1]:.6g}"),
            ("v1_after  mean [m/s]", f"{v1a[0]:.6g}, {v1a[1]:.6g}"),
            ("omega0_before mean [deg/s]", f"{o0b:.6g}"),
            ("omega0_after  mean [deg/s]", f"{o0a:.6g}"),
            ("omega1_before mean [deg/s]", f"{o1b:.6g}"),
            ("omega1_after  mean [deg/s]", f"{o1a:.6g}"),
            ("I (ring) [kg·m²] disk 0,1", f"{INERTIA[0]:.6g}, {INERTIA[1]:.6g}"),
            ("Masses [kg] disk 0,1", f"{MASS[0]:.6g}, {MASS[1]:.6g}"),
            ("Radius [m]", f"{RADIUS_M:.6g}"),
        ]
        pd.DataFrame(rows, columns=["Quantity","Value"]).to_excel(writer, index=False, sheet_name="Results")

    # -----------------------------
    # Short console summary
    # -----------------------------
    print(f"Collision frame (excluded): {cf}")
    print(f"e = {e:.6g} | Momentum error = {p_err:.6g} | Energy drop = {K_drop:.6g}")
    print(f"Wrote: {OUTPUT_XLSX}")
    print("Energy drop (rel, COM frame)", f"{K_drop_COM:.6g}")


if __name__ == "__main__":
    main()
