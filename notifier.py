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

import requests

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_URL = "https://ntfy.sh"


def _send(video_name, results_df, raw_summary):
    try:
        lines = []
        if results_df is not None:
            for row in results_df.itertuples(index=False):
                lines.append(f"{row.Quantity}: {row.Value}")
        else:
            lines.append("(no Results sheet -- metrics weren't computed)")
        lines.append("")
        lines.append(
            f"Raw_Data: {raw_summary['total_rows']} rows "
            f"(disk0={raw_summary['disk0_rows']}, disk1={raw_summary['disk1_rows']})"
        )
        theta_counts = ", ".join(
            f"{k}={v}" for k, v in raw_summary["theta_source_counts"].items()
        )
        lines.append(f"theta_source: {theta_counts}")
        message = "\n".join(lines)

        headers = {
            "Title": f"DEM run complete: {video_name}",
            "Priority": "default",
            "Tags": "test_tube",
        }
        requests.post(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
    except Exception:
        pass


def notify_run_complete(video_name, results_df, raw_summary):
    """
    Push a summary of the Results sheet (restitution/momentum/energy/gap/
    interpolation %) plus a Raw_Data coverage summary to the phone via
    ntfy.sh -- metrics only (user, 2026-09-23), never the raw per-frame data
    or the .xlsx file itself.

    results_df: the "Quantity"/"Value" DataFrame from build_student_excel's
        Results sheet, or None if metrics weren't computed.
    raw_summary: dict with total_rows, disk0_rows, disk1_rows,
        theta_source_counts (see build_student_excel).
    """
    if not NTFY_TOPIC:
        return
    threading.Thread(
        target=_send, args=(video_name, results_df, raw_summary), daemon=True
    ).start()
