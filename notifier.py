# Best-effort push notification (ntfy.sh) for finished DEM analysis runs.
#
# Setup (one-time, per machine): install the "ntfy" app on your phone
# (Android/iOS), subscribe to a topic name of your choice -- pick something
# long/hard-to-guess, since ntfy.sh topics are unauthenticated (anyone who
# knows the name can read or post to it) -- and set NTFY_TOPIC (see
# .env.example).
#
# If NTFY_TOPIC isn't set, notify_run_complete() is a silent no-op, so the
# analysis pipeline behaves identically whether or not this is configured.
# Any failure here (no network, ntfy.sh down, etc.) is swallowed -- a failed
# notification must never break the actual analysis run. The actual network
# call runs on a background thread (fire-and-forget, nothing here has a
# return value the caller needs) so it can never block the GUI thread that
# build_student_excel runs on.

import os
import threading

import numpy as np
import requests

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_URL = "https://ntfy.sh"


def _fmt_bool(value):
    return "TRUE" if value else "FALSE"


def _fmt_frac_pct(value):
    """value is a fraction (e.g. 0.05 -> 5.00%)."""
    return f"{value * 100:.2f}%" if value is not None and np.isfinite(value) else str(value)


def _fmt_pct(value):
    """value is already a percentage (e.g. 5.0 -> 5.00%)."""
    return f"{value:.2f}%" if value is not None and np.isfinite(value) else str(value)


def _build_message(raw_summary, metrics, interpolated_pct):
    theta_counts = raw_summary["theta_source_counts"]
    measured = theta_counts.get("measured", 0)
    interpolated = theta_counts.get("interpolated", 0)

    lines = [
        "",
        "Raw Data:",
        f"Total Rows = {raw_summary['total_rows']}",
        f"BLUE Rows = {raw_summary['disk1_rows']}",
        f"GREEN Rows = {raw_summary['disk0_rows']}",
        f"Measured = {measured}",
        f"Interpolated = {interpolated}",
    ]

    if metrics is not None:
        e = metrics["restitution_e"]
        gap = metrics["collision_gap_mm"]
        lines.append(f"Collision Frame = {metrics['collision_frame']}")
        lines.append("")
        lines.append("Metrics:")
        lines.append(f"e = {e:.6g}" if np.isfinite(e) else f"e = {e}")
        lines.append(f"Momentum Error = {_fmt_frac_pct(metrics['momentum_error_rel'])}")
        lines.append(f"Energy Drop = {_fmt_frac_pct(metrics['energy_drop_rel_COM'])}")
        lines.append(f"Collision Gap = {gap:.2f} mm" if np.isfinite(gap) else f"Collision Gap = {gap}")
        lines.append(f"Collision Gap Warning = {_fmt_bool(metrics['collision_gap_warning'])}")
    else:
        lines.append("Collision Frame = N/A")
        lines.append("")
        lines.append("Metrics: (not computed)")

    lines.append(f"Theta Interpolation = {_fmt_pct(interpolated_pct)}")

    return "\n".join(lines)


def _send(group_name, raw_summary, metrics, interpolated_pct):
    try:
        message = _build_message(raw_summary, metrics, interpolated_pct)

        headers = {
            "Title": f"Collision Run Completed: {group_name}",
            "Priority": "default",
        }
        requests.post(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
    except Exception:
        pass


def notify_run_complete(group_name, raw_summary, metrics, interpolated_pct):
    """
    Push a run-complete summary to the phone via ntfy.sh -- metrics only
    (user, 2026-09-23), never the raw per-frame data or the .xlsx file
    itself. Message format is fixed to match ToDo.md's "Style of Notifier
    POSTs" spec exactly -- don't reformat without updating that spec too.
    The "Collision Run Completed: {group_name}" line lives only in the ntfy
    `Title` header (_send), not in the body -- ntfy renders both, so
    duplicating it in the body made it show twice in the notification.

    group_name: the student group name (Page 3 `group_val`), used to
        identify the run -- NOT the video/CSV filename, which is always the
        fixed "disk_tracks" workspace file and was never a useful identifier.
    raw_summary: dict with total_rows, disk0_rows, disk1_rows,
        theta_source_counts (see build_student_excel). disk0=Green,
        disk1=Blue.
    metrics: the dict returned by Post_process._compute_metrics, or None if
        metrics weren't computed (include_metrics=False).
    interpolated_pct: theta interpolation percentage (0-100) from
        build_student_excel.
    """
    if not NTFY_TOPIC:
        return
    threading.Thread(
        target=_send, args=(group_name, raw_summary, metrics, interpolated_pct), daemon=True
    ).start()
