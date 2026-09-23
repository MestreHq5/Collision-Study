# Best-effort push notification (ntfy.sh) for finished DEM analysis runs.
#
# Setup (one-time, per machine):
#   1. Install the "ntfy" app on your phone (Android/iOS) and subscribe to a
#      topic name of your choice -- pick something long/hard-to-guess, since
#      ntfy.sh topics are unauthenticated (anyone who knows the name can read
#      or post to it).
#   2. setx NTFY_TOPIC "your-chosen-topic-name"   (restart your terminal/IDE
#      afterwards -- setx only affects new processes)
#
# If NTFY_TOPIC isn't set, notify_run_complete() is a silent no-op, so the
# analysis pipeline behaves identically whether or not this is configured.
# Any failure here (no network, ntfy.sh down, etc.) is swallowed -- a failed
# notification must never break the actual analysis run.

import os
from pathlib import Path

import requests

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_URL = "https://ntfy.sh"
_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # ntfy.sh default attachment cap


def notify_run_complete(video_name, results_df, raw_summary, xlsx_path=None):
    """
    Push a summary of the Results sheet (restitution/momentum/energy/gap) plus
    a Raw_Data coverage summary to the phone via ntfy.sh. Attaches the actual
    .xlsx file when it's under ntfy's size cap, so both sheets are reachable
    from the notification itself.

    results_df: the "Quantity"/"Value" DataFrame from build_student_excel's
        Results sheet, or None if include_metrics=False.
    raw_summary: dict with total_rows, disk0_rows, disk1_rows,
        theta_source_counts (see build_student_excel).
    """
    if not NTFY_TOPIC:
        return
    try:
        lines = []
        if results_df is not None:
            for row in results_df.itertuples(index=False):
                lines.append(f"{row.Quantity}: {row.Value}")
        else:
            lines.append("(no Results sheet -- include_metrics was False)")
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

        attach = (
            xlsx_path
            and os.path.exists(xlsx_path)
            and os.path.getsize(xlsx_path) <= _MAX_ATTACHMENT_BYTES
        )
        if attach:
            headers["Filename"] = Path(xlsx_path).name
            headers["Message"] = message
            with open(xlsx_path, "rb") as f:
                requests.post(
                    f"{NTFY_URL}/{NTFY_TOPIC}", data=f, headers=headers, timeout=15
                )
        else:
            requests.post(
                f"{NTFY_URL}/{NTFY_TOPIC}",
                data=message.encode("utf-8"),
                headers=headers,
                timeout=15,
            )
    except Exception:
        pass
