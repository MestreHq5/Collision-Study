#!/usr/bin/env python3
import math
import numpy as np
import pandas as pd
from numpy.polynomial.polynomial import polyfit

# -----------------------------
# User constants
# -----------------------------
CSV_PATH = "disk_tracks.csv"
OUTPUT_XLSX = "analysis_results_hybrid.xlsx"

FPS = 30                   # frames per second
RADIUS_M = 0.040               # 40 mm
MASS = {0: 0.0118, 1: 0.0118}  # kg (11.8 g)
INERTIA = {i: MASS[i] * RADIUS_M**2 for i in (0, 1)}  # thin ring: I = m R^2

REQ_COLS = ["frame","disk_id","cx_mm","cy_mm","mx_mm","my_mm","r_px","marker_color"]
TOL = 1e-12

# -----------------------------
# Helpers
# -----------------------------
def ensure_sorted(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values("frame").reset_index(drop=True)

def to_meters(df_raw: pd.DataFrame) -> pd.DataFrame:
    df = df_raw.copy()
    df["cx"] = df["cx_mm"] / 1000.0
    df["cy"] = df["cy_mm"] / 1000.0
    df["mx"] = df["mx_mm"] / 1000.0
    df["my"] = df["my_mm"] / 1000.0
    return df

def unwrap_angle(dfm: pd.DataFrame) -> np.ndarray:
    dx = dfm["mx"] - dfm["cx"]
    dy = dfm["my"] - dfm["cy"]
    return np.unwrap(np.arctan2(dy, dx))

def linreg_slope(x: pd.Series, y: pd.Series) -> float:
    x, y = np.asarray(x,float), np.asarray(y,float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if x.size < 2:
        return float("nan")
    b, a = polyfit(x, y, 1)
    return float(b)

def find_collision_frame(df0m: pd.DataFrame, df1m: pd.DataFrame) -> int:
    m = pd.merge(df0m[["frame","cx","cy"]], df1m[["frame","cx","cy"]],
                 on="frame", how="inner", suffixes=("_0","_1"))
    dist = np.hypot(m["cx_1"] - m["cx_0"], m["cy_1"] - m["cy_0"])
    return int(m.loc[dist.idxmin(),"frame"])

def velocities_from_regressions(dfm: pd.DataFrame, cf: int) -> dict:
    t = dfm["frame"] / FPS
    before, after = dfm["frame"] < cf, dfm["frame"] > cf
    vx_b = linreg_slope(t[before], dfm.loc[before,"cx"])
    vy_b = linreg_slope(t[before], dfm.loc[before,"cy"])
    vx_a = linreg_slope(t[after],  dfm.loc[after,"cx"])
    vy_a = linreg_slope(t[after],  dfm.loc[after,"cy"])
    theta = unwrap_angle(dfm)
    w_b = math.degrees(linreg_slope(t[before], theta[before]))
    w_a = math.degrees(linreg_slope(t[after],  theta[after]))
    return {"vx_b":vx_b,"vy_b":vy_b,"vx_a":vx_a,"vy_a":vy_a,
            "omega_b_deg":w_b,"omega_a_deg":w_a}

def finite_diff_vels(dfm: pd.DataFrame) -> pd.DataFrame:
    """Return per-frame finite-difference velocities vx,vy (aligned to later frame)."""
    out = dfm.copy()
    out["vx"] = dfm["cx"].diff() * FPS
    out["vy"] = dfm["cy"].diff() * FPS
    return out

def median_window_vel(dfm: pd.DataFrame, cf: int, side: str, win: int=5):
    if side=="before":
        mask = (dfm["frame"] < cf) & (dfm["frame"] >= cf - win)
    else: # after
        mask = (dfm["frame"] > cf) & (dfm["frame"] <= cf + win)
    vx = dfm.loc[mask,"vx"].median()
    vy = dfm.loc[mask,"vy"].median()
    return np.array([vx,vy],float)

def restitution_from_fd(df0m: pd.DataFrame, df1m: pd.DataFrame, cf: int, win: int=5) -> float:
    # build per-frame finite difference velocities
    d0 = finite_diff_vels(df0m)
    d1 = finite_diff_vels(df1m)
    v0b = median_window_vel(d0, cf, "before", win)
    v0a = median_window_vel(d0, cf, "after",  win)
    v1b = median_window_vel(d1, cf, "before", win)
    v1a = median_window_vel(d1, cf, "after",  win)
    # line of centers
    p0c = df0m.loc[df0m["frame"]==cf, ["cx","cy"]].iloc[0].values
    p1c = df1m.loc[df1m["frame"]==cf, ["cx","cy"]].iloc[0].values
    n = (p1c - p0c) / (np.linalg.norm(p1c-p0c) + TOL)
    vrel_b = v1b - v0b; vrel_a = v1a - v0a
    vnb = -float(np.dot(vrel_b,n)); vna = float(np.dot(vrel_a,n))
    if vnb <= TOL or not np.isfinite(vna): return float("nan")
    return vna/vnb

def kinetic_linear(m,vx,vy):
    return 0.5*m*(vx*vx+vy*vy) if np.isfinite(vx) and np.isfinite(vy) else float("nan")

def kinetic_rot(I,omega_deg):
    if not np.isfinite(omega_deg): return float("nan")
    w = math.radians(omega_deg)
    return 0.5*I*w*w

# -----------------------------
# Main
# -----------------------------
def main():
    df = pd.read_csv(CSV_PATH)
    for c in REQ_COLS:
        if c not in df.columns: raise ValueError(f"CSV missing {c}")

    df0_raw = ensure_sorted(df[df["disk_id"]==0].copy())
    df1_raw = ensure_sorted(df[df["disk_id"]==1].copy())
    df0m = to_meters(df0_raw); df1m = to_meters(df1_raw)
    df0m["t"] = df0m["frame"]/FPS; df0m["theta"]=unwrap_angle(df0m)
    df1m["t"] = df1m["frame"]/FPS; df1m["theta"]=unwrap_angle(df1m)

    cf = find_collision_frame(df0m, df1m)

    # regressions for momentum & energy
    v0 = velocities_from_regressions(df0m, cf)
    v1 = velocities_from_regressions(df1m, cf)
    v0b_full = np.array([v0["vx_b"],v0["vy_b"]]); v0a_full = np.array([v0["vx_a"],v0["vy_a"]])
    v1b_full = np.array([v1["vx_b"],v1["vy_b"]]); v1a_full = np.array([v1["vx_a"],v1["vy_a"]])

    # restitution from finite-difference medians
    e = restitution_from_fd(df0m, df1m, cf, win=5)

    # momentum error (regression velocities)
    p_before = MASS[0]*v0b_full + MASS[1]*v1b_full
    p_after  = MASS[0]*v0a_full + MASS[1]*v1a_full
    p_err = np.linalg.norm(p_after-p_before)/(np.linalg.norm(p_before)+TOL)

    # energies (regressions)
    o0b,o0a,o1b,o1a = v0["omega_b_deg"],v0["omega_a_deg"],v1["omega_b_deg"],v1["omega_a_deg"]
    Kb = kinetic_linear(MASS[0],v0["vx_b"],v0["vy_b"]) + kinetic_linear(MASS[1],v1["vx_b"],v1["vy_b"]) \
       + kinetic_rot(INERTIA[0],o0b) + kinetic_rot(INERTIA[1],o1b)
    Ka = kinetic_linear(MASS[0],v0["vx_a"],v0["vy_a"]) + kinetic_linear(MASS[1],v1["vx_a"],v1["vy_a"]) \
       + kinetic_rot(INERTIA[0],o0a) + kinetic_rot(INERTIA[1],o1a)
    K_drop = (Kb-Ka)/(Kb+TOL)

    # COM frame energies
    Vcm_b = (MASS[0]*v0b_full+MASS[1]*v1b_full)/(MASS[0]+MASS[1])
    Vcm_a = (MASS[0]*v0a_full+MASS[1]*v1a_full)/(MASS[0]+MASS[1])
    v0b_c,v1b_c = v0b_full-Vcm_b,v1b_full-Vcm_b
    v0a_c,v1a_c = v0a_full-Vcm_a,v1a_full-Vcm_a
    Kb_com = kinetic_linear(MASS[0],*v0b_c)+kinetic_linear(MASS[1],*v1b_c)+kinetic_rot(INERTIA[0],o0b)+kinetic_rot(INERTIA[1],o1b)
    Ka_com = kinetic_linear(MASS[0],*v0a_c)+kinetic_linear(MASS[1],*v1a_c)+kinetic_rot(INERTIA[0],o0a)+kinetic_rot(INERTIA[1],o1a)
    K_drop_COM = (Kb_com-Ka_com)/(Kb_com+TOL)

    # Write Excel
    with pd.ExcelWriter(OUTPUT_XLSX,engine="openpyxl") as writer:
        df0_raw.to_excel(writer,index=False,sheet_name="puck_0")
        df1_raw.to_excel(writer,index=False,sheet_name="puck_1")
        rows = [
            ("Collision frame (excluded)",cf),
            ("e (restitution, FD medians 5)",f"{e:.6g}"),
            ("Momentum error (regressions)",f"{p_err:.6g}"),
            ("Energy drop (lab, regressions)",f"{K_drop:.6g}"),
            ("Energy drop (COM, regressions)",f"{K_drop_COM:.6g}"),
        ]
        pd.DataFrame(rows,columns=["Quantity","Value"]).to_excel(writer,index=False,sheet_name="Results")

    # Console
    print(f"Collision frame (excluded): {cf}")
    print(f"e = {e:.6g} | Momentum error = {p_err:.6g} | Energy drop = {K_drop:.6g}")
    print(f"Energy drop (rel, COM frame) {K_drop_COM:.6g}")
    print(f"Wrote: {OUTPUT_XLSX}")

if __name__=="__main__":
    main()


