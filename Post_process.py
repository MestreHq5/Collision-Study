# Use for results mix, total and regression

import math
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# CSV and Excel Collums
REQ_COLS = ["frame","disk_id","cx_mm","cy_mm","mx_mm","my_mm","r_px"]

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
    dx = dfm["mx"] - dfm["cx"]
    dy = dfm["my"] - dfm["cy"]
    return np.unwrap(np.arctan2(dy, dx))


def _compute_vels(df_m: pd.DataFrame, fps: float) -> pd.DataFrame:
    """
    Finite-difference linear v, and angular speed from unwrapped marker angle.
    Matches your results_total approach.
    """
    out = df_m.copy()
    # Linear finite differences (m/s), aligned to later frame
    out["vx"] = out["cx"].diff() * fps
    out["vy"] = out["cy"].diff() * fps

    # Angular from marker vector
    theta = np.arctan2(out["my"] - out["cy"], out["mx"] - out["cx"]).to_numpy()
    theta_unwrapped = np.unwrap(theta)                 # radians
    dtheta = np.full(len(out), np.nan, dtype=float)    # length N
    if len(out) > 1:
        dtheta[1:] = np.diff(theta_unwrapped)          # put N-1 diffs starting at index 1
    out["omega_deg_s"] = np.degrees(dtheta) * fps      # deg/s, aligned to later frame
    out["theta_unwrapped_deg"] = np.degrees(theta_unwrapped)  # for students
    return out


def _find_collision_frame(df0m: pd.DataFrame, df1m: pd.DataFrame) -> int:
    """
    Forced-unique collision frame = frame of minimal center-to-center distance.
    """
    m = pd.merge(df0m[["frame","cx","cy"]], df1m[["frame","cx","cy"]],
                 on="frame", suffixes=("_0","_1"))
    dx = m["cx_1"] - m["cx_0"]
    dy = m["cy_1"] - m["cy_0"]
    return int(m.loc[np.hypot(dx, dy).idxmin(), "frame"])

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
    v0b = (df0m.loc[before0, ["vx","vy"]].mean().fillna(np.nan).values)
    v0a = (df0m.loc[after0,  ["vx","vy"]].mean().fillna(np.nan).values)
    v1b = (df1m.loc[before1, ["vx","vy"]].mean().fillna(np.nan).values)
    v1a = (df1m.loc[after1,  ["vx","vy"]].mean().fillna(np.nan).values)

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

    v0x_b = (m.loc[mb, "vx0"] - Vcm_x.loc[mb]).median()
    v0y_b = (m.loc[mb, "vy0"] - Vcm_y.loc[mb]).median()
    v1x_b = (m.loc[mb, "vx1"] - Vcm_x.loc[mb]).median()
    v1y_b = (m.loc[mb, "vy1"] - Vcm_y.loc[mb]).median()

    v0x_a = (m.loc[ma, "vx0"] - Vcm_x.loc[ma]).median()
    v0y_a = (m.loc[ma, "vy0"] - Vcm_y.loc[ma]).median()
    v1x_a = (m.loc[ma, "vx1"] - Vcm_x.loc[ma]).median()
    v1y_a = (m.loc[ma, "vy1"] - Vcm_y.loc[ma]).median()

    o0b_med = float(df0m.loc[df0m["frame"] < cf, "omega_deg_s"].median())
    o0a_med = float(df0m.loc[df0m["frame"] > cf, "omega_deg_s"].median())
    o1b_med = float(df1m.loc[df1m["frame"] < cf, "omega_deg_s"].median())
    o1a_med = float(df1m.loc[df1m["frame"] > cf, "omega_deg_s"].median())

    Kb_com = 0.5*MASS[0]*(v0x_b**2 + v0y_b**2) + 0.5*MASS[1]*(v1x_b**2 + v1y_b**2)
    Ka_com = 0.5*MASS[0]*(v0x_a**2 + v0y_a**2) + 0.5*MASS[1]*(v1x_a**2 + v1y_a**2)

    def _K_rot(I, omega_deg):
        w = math.radians(omega_deg) if np.isfinite(omega_deg) else np.nan
        return 0.5*I*(w**2) if np.isfinite(w) else np.nan

    Kr0b = _K_rot(INERTIA[0], o0b_med)
    Kr1b = _K_rot(INERTIA[1], o1b_med)
    Kr0a = _K_rot(INERTIA[0], o0a_med)
    Kr1a = _K_rot(INERTIA[1], o1a_med)

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
    """
    Open the CSV and produce a trajectory image with the collision frame highlighted.
    Returns the collision frame (int).
    """
    csvp = Path(csv_path)
    if not csvp.exists():
        raise FileNotFoundError(csvp.resolve())

    df = pd.read_csv(csvp)
    missing = [c for c in REQ_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")

    df0 = _ensure_sorted(df[df["disk_id"]==0].copy())
    df1 = _ensure_sorted(df[df["disk_id"]==1].copy())
    df0m = _add_meter_cols(df0)
    df1m = _add_meter_cols(df1)

    cf = _find_collision_frame(df0m, df1m)

    p0 = df0m.loc[df0m["frame"]==cf, ["cx","cy"]].head(1)
    p1 = df1m.loc[df1m["frame"]==cf, ["cx","cy"]].head(1)

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(df0m["cx"], df0m["cy"], label="disk 0 trajectory")
    ax.plot(df1m["cx"], df1m["cy"], label="disk 1 trajectory")

    if not p0.empty:
        ax.scatter(p0["cx"], p0["cy"], s=80, marker="o", edgecolors="k",
                   label=f"collision @ disk 0 (f={cf})")
    if not p1.empty:
        ax.scatter(p1["cx"], p1["cy"], s=80, marker="s", edgecolors="k",
                   label=f"collision @ disk 1 (f={cf})")

    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    if show_equal_aspect:
        ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    if show_title:
        ax.set_title("Puck trajectories with collision frame highlighted")

    outp = Path(output_image_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(outp, dpi=200)
    plt.close(fig)

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
