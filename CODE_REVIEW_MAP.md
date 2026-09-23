# Code Review Map

Reference for a manual, file-by-file comment/code review of the pipeline. For each file:
what it's for, every function/class it defines (one line each), and a line count. Line
counts are `total` / `code` where `code` = total minus blank lines minus lines that are
*entirely* a comment (a trailing `# ...` on a code line still counts as code) — a rough
"how much is actually logic" number, not exact.

Generated 2026-09-23 against `gr/tweaks`. Re-generate (`wc -l`, `grep '^def \|^class \|^    def '`)
if the file list or function set changes meaningfully before you finish the pass.

## Reading/runtime order

```
initializer.py
  └─ app.py            (GUI shell: MainWindow, main())
       └─ helper.py     (button handlers -> backend calls)
            ├─ detector.py       (Page 5 "Generate": video -> disk_tracks.csv)
            │    └─ Pre_process.py   (CV primitives detector.py calls into)
            └─ Post_process.py  (Page 5 "Preview"/genData: csv -> plot / data.xlsx)
                 └─ notifier.py      (last step of build_student_excel)
```

This is also the suggested review order below: it follows one run of the app from launch
to the final `.xlsx`, so each file's callers are already fresh in mind before you open it.

---

## 1. `initializer.py` — 18 / 7 lines

Entry point only. No functions defined.

- Loads `.env` (via `python-dotenv`) into `os.environ` **before** `import app`, because
  `app.py`'s own import chain (`Post_process` → `notifier`) reads `NTFY_TOPIC` from the
  environment at module load time — has to happen first or the notifier silently never sees it.
- `if __name__ == "__main__": app.main()`

## 2. `app.py` — 317 / 203 lines

The Qt GUI shell: window construction, widget lookup/wiring, page navigation. Almost no
business logic lives here — that's `helper.py`.

| Function/class | Purpose |
|---|---|
| `resource_path(*parts)` | Resolves a bundled-resource path, dev vs. PyInstaller frozen (`sys._MEIPASS`) |
| `_position_console_right(available, app_width)` | Best-effort: moves the auto-spawned console window into the right half of the screen for a built `--console` exe |
| `class MainWindow(QMainWindow)` | | 
| &nbsp;&nbsp;`__init__` | Loads `gui.ui`, sizes/positions window (left half of screen), installs `hp.PrintTee` on stdout, finds every named widget across Pages 1–6, wires nav/action button `clicked` signals, sets initial page/state |
| &nbsp;&nbsp;`resizeEvent` | Debounced (120ms `QTimer.singleShot`) re-render of the trajectory preview on window resize, to avoid `QPainter` errors from resizing a pixmap mid-drag |
| &nbsp;&nbsp;`_on_gen_progress/_on_gen_finished/_on_gen_failed/_on_log_line` | Thin bound-method wrappers so `DetectionWorker`'s cross-thread Qt signals land on real `QObject` methods (required for Qt's thread-affinity auto-detection) |
| &nbsp;&nbsp;`select_video_file` | Opens file dialog, copies the chosen video into the run workspace, reads native FPS via OpenCV, updates the Page 4 status label, enables Proceed |
| `main()` | Sets the HiDPI rounding policy, builds `QApplication`/`MainWindow`, runs the Qt event loop |

## 3. `helper.py` — 370 / 275 lines

The actual glue behind every button `app.py` wires up — reads/validates form fields, calls
into `detector`/`Post_process`, updates widget state. This is where "what does clicking X
actually do" lives.

| Function/class | Purpose |
|---|---|
| `class PrintTee(QObject)` | Tees `sys.stdout`; re-emits only bracket-tagged (`[INFO]`/`[WARN]`/`[ERROR]`) lines as a `pyqtSignal` so Page 5's log box can show them, cross-thread-safe |
| &nbsp;&nbsp;`write/flush/isatty` | Stream interface `PrintTee` needs to stand in for `sys.stdout` |
| `resource_path(*parts)` | Same bundled-resource resolver as `app.py`'s, duplicated here for helper's own use |
| `file_manager(parent_folder, child_folder)` | Creates/returns the per-group workspace dir (`Desktop/<parent>/<child>` or `DEM_WORKSPACE_ROOT` override) |
| `validate_input(group, massB, massG, radiusB, radiusG)` | Validates Page 3's form fields, returns an error string or `""` |
| `eraser(self)` | Clears Page 3's input fields |
| `validator(self)` | Reads Page 3 fields, validates, creates the run workspace, advances to Page 4 or shows the warning |
| `class DetectionWorker(QThread)` | Runs `detector.main()` off the GUI thread |
| &nbsp;&nbsp;`__init__/_on_progress/run` | Stores run params; throttles `progress` emits to whole-percent changes; runs `detector.main()`, catching exceptions into an `error` signal |
| `generate(self)` | Starts a `DetectionWorker` for the loaded video, wires its signals to `MainWindow`'s bound slots |
| `_update_progress/_generation_finished/_generation_failed` | GUI-thread slots: update progress bar/buttons/status bar from `DetectionWorker`'s signals |
| `_trajectory_figsize_for_label(self)` | Computes a matplotlib `figsize` matching `detectionLabel`'s current aspect ratio, so `visualize_trajectories`' plot doesn't get Qt-letterboxed |
| `preview(self)` | Renders the trajectory plot (`Post_process.visualize_trajectories`) and shows it, keeping the full-res pixmap around |
| `apply_trajectory_pixmap(self)` | Re-renders/rescales the trajectory pixmap to `detectionLabel`'s current size (called on resize) |
| `genData(self)` | Reads mass/radius fields, calls `Post_process.build_student_excel` to produce `data.xlsx`, updates button state |
| `analisysPage(self)` | Resets Page 5's UI state when the user proceeds there |
| `redo(self)` | Sends the user back to the data-input page (Page 2) |
| `scaler(self)` | Scales/applies the IST logo pixmap onto Page 1 and Page 6 |

## 4. `detector.py` — 786 / 485 lines

The core detection pipeline: turns a video into `disk_tracks.csv` (+ an annotated
`detection.mp4`). Heavily commented — most of the file's "non-code" lines are calibration
rationale for the constants block, not narrative filler.

| Function/class | Purpose |
|---|---|
| *(module constants)* | Frame/blur/mass/geometry constants, HSV color ranges (`GREEN_/BLUE_LOWER/UPPER`), marker shape/darkness gates, fallback/ID-tracking gate distances — see CLAUDE.md "Marker detection" for the calibration numbers behind these |
| `remove_duplicate_detections(disks, dist_threshold)` | Keeps the highest-confidence detection among any cluster of near-duplicate boxes |
| `fallback_contour_disks(frame, background, existing_disks, prev_pos, missing_ids, ...)` | Background-subtraction fallback, only searched near a missing disk's *predicted* position, radius-gated against glare blobs |
| `resolve_marker(frame, det, scale_mm_per_px)` | Resolves a detection's disk identity (reusing `det["color"]` if already known) + its dimple marker position via `Pre_process` |
| `detect_disks_color(frame, color_ranges)` | Primary HSV position detector; includes the identify-by-exclusion fallback for a glare-desaturated disk |
| `class IDAssigner` | Stable 0/1 ID tracker across frames |
| &nbsp;&nbsp;`__init__` | Sets up `prev_pos`/`prev_prev_pos`/`gap` bookkeeping |
| &nbsp;&nbsp;`_dist(a, b)` | Euclidean distance (static) |
| &nbsp;&nbsp;`_current_gap(pid)` | Frames-missing count for `pid`, including the frame currently being resolved |
| &nbsp;&nbsp;`predicted_pos(pid)` | Extrapolates `pid`'s expected current position from its last known velocity × gap |
| &nbsp;&nbsp;`assign(detections)` | The 4-step assignment: position-lock → color-first → velocity-gated nearest-neighbor to predicted position → deterministic left-right fallback for genuinely new tracks |
| `info(info_type, message)` | `[TAG] message` print helper |
| `main(video_path, bg_path, dtc_path, csv_path, fps_eff, progress_callback=None)` | Full pipeline entry: background estimate → open video → per-frame loop (detect → dedup → fallback → scale calibration → marker resolve → ID assign → annotate/write frame → CSV row) → write `disk_tracks.csv` |
| &nbsp;&nbsp;`_puck_masker(frame)` *(nested in `main`)* | Closure passed to `estimate_background_median` so already-on-table pucks don't get baked into the background |

## 5. `Pre_process.py` — 611 / 475 lines

Low-level CV primitives `detector.py` calls into. No knowledge of IDs/tracking/CSV — pure
per-frame image operations.

| Function | Purpose |
|---|---|
| `estimate_background_median(video_path, clean_seconds, ...)` | Median-of-sampled-frames background estimate; optional `puck_masker` excludes detected-puck pixels per sampled frame from the median |
| `segment_disks(frame, background, ...)` | Background-subtraction + threshold (with an Otsu fallback) + contour position detector — backs `fallback_contour_disks` |
| `segment_disks_by_color(frame, color_ranges, ...)` | Primary HSV color-contour position detector (per-color mask → contours → radius/circularity gates) |
| `_select_best_blob(raw_mask, x1, y1, mask_center, mask_radius, mask_inner_radius, disk_radius, min_area, min_circularity, max_circularity, max_area=None)` | Shared marker-detection back half: restrict candidate mask to inside-disk (optionally an annulus), clean up, pick the largest contour that *also* passes the shape gate |
| `detect_dark_marker_center(frame, disk_center, disk_radius, ...)` | Finds the dark dimple marker via a threshold relative to the disk's own median V, with one optional bounded "relaxed" retry (`relax_frac_delta` + `max_area`) |
| `classify_disk_bulk_color(frame, disk_center, disk_radius, color_ranges, ...)` | Disk identity via majority-vote HSV match over the whole disk interior |
| `calibrate_hsv_range(video_path, frame_index=0, box=6)` | Interactive dev tool: click a frame, prints a suggested HSV `(lower, upper)` range to paste into `detector.py` |
| &nbsp;&nbsp;`on_click(event, x, y, flags, param)` *(nested)* | OpenCV mouse callback backing the tool above |

## 6. `Post_process.py` — 900 / 687 lines

Everything downstream of the CSV: kinematics, rotation fitting, collision metrics,
trajectory plot, and the final Excel export. The largest and most math-dense file —
budget the most review time here, especially the rotation-fit and `_compute_metrics`
sections (dense docstrings recording *why*, worth checking they still match the code).

| Function | Purpose |
|---|---|
| `_ensure_sorted(df)` | Sort by `frame`, reset index |
| `_add_meter_cols(df_raw)` | Adds `cx/cy/mx/my` (meters) from the `_mm` CSV columns |
| `_unwrap_angle(dfm)` | NaN-safe `np.unwrap` of the marker angle (plain `np.unwrap` poisons everything after the first gap) |
| `_compute_vels(df_m, fps)` | Finite-difference `vx/vy`/`omega_deg_s`, divided by *actual* elapsed frames (`frame.diff()`), not a hardcoded 1 |
| `_sigma_clip_linear_fit(x, y, n_sigma=2.5, max_iters=10, min_points=4)` | Iterative sigma-clipped linear regression; returns `residual_std` so callers can gate trust beyond "0 outliers" |
| `_wrap_pi(a)` | Wraps radians into `(-pi, pi]` |
| `_robust_omega_seed(frame, theta_wrapped, ...)` | Branch-safe initial ω estimate from short-gap wrapped pairwise slopes (no global sequential unwrap) |
| `_robust_unwrap_and_fit(frame, theta_wrapped, ...)` | Combined branch-robust unwrap + sigma-clip fit — avoids the sequential-unwrap branch-flip failure mode |
| `fit_rotation_segments(dfm, collision_frame, ...)` | Per-disk, per-segment (before/after collision, never across it) rotation fit; adds `theta_unwrapped_deg`, `rotation_segment`, `theta_trend_consistent`, `omega_fit_deg_per_frame`, `theta_fit_intercept_deg`, `omega_fit_residual_std_deg` |
| `_rotation_segment_summary(out)` | Per-segment ω + inlier/outlier/missing counts from the above |
| `fit_rotation(df0_raw, df1_raw, ...)` | Two-disk entry point: shares one collision frame, returns `(out0, out1, summary)` |
| `_find_collision_frame(df0m, df1m)` | Frame of minimal center-to-center distance |
| `_safe_vxvy_mean(df, mask)` / `_safe_median(series)` | NaN/empty-slice-safe aggregation (suppresses the expected "Mean of empty slice" warning) |
| `_compute_metrics(df0m, df1m, masses, radius, fps)` | Computes restitution `e` (impulse-direction normal, not position-based), momentum error, COM-frame energy drop (incl. rotational KE), `collision_gap_mm` diagnostic + warning |
| &nbsp;&nbsp;`_segment_omega_deg_s(...)` / `_K_rot(I, omega_deg)` *(nested)* | Prefer the fitted ω over the raw median when available; rotational KE from inertia + ω |
| `visualize_trajectories(csv_path, output_image_path, fps=30.0, ...)` | Renders/saves the trajectory PNG (matplotlib `Agg`), returns the collision frame |
| `_drop_fallback_rows(df)` | Excludes `source == "contour_fallback"` rows before any velocity/energy calc |
| `_fill_theta_gaps_per_disk(tbl, cf)` | Per-segment linear interpolation guaranteeing a `theta_deg` on every exported row; tags `theta_source` (`measured`/`interpolated`/`collision_nearest`/`None`) |
| `build_student_excel(csv_path, output_xlsx_path, masses, radius, fps=30.0, include_metrics=False)` | Top-level export: builds the `Raw_Data` sheet, optionally computes metrics for the `Results` sheet (only written if `DEM_SHOW_RESULTS_SHEET=1`) and the notifier, calls `notify_run_complete`. Returns the collision frame |

## 7. `notifier.py` — 76 / 52 lines

Best-effort ntfy.sh push notification, called from the very end of `build_student_excel`.

| Function | Purpose |
|---|---|
| `_send(video_name, results_df, raw_summary)` | Builds the notification body from `results_df` + `raw_summary`, POSTs to `ntfy.sh`, swallows every failure |
| `notify_run_complete(video_name, results_df, raw_summary)` | Public entry: no-op if `NTFY_TOPIC` unset, otherwise fires `_send` on a daemon thread (fire-and-forget) |

---

## Review roadmap

Suggested pass order, following one run of the app start to finish — each stage's inputs
are whatever the previous stage produced, so reading in this order means you're never
looking at a function before you've seen where its inputs come from.

1. **`initializer.py`** — 2 minutes. Just confirm the `.env`-before-`import app` ordering
   comment still matches reality if you touch import order anywhere later.

2. **`app.py`** — window/widget wiring. Read `MainWindow.__init__` against `gui.ui`'s page
   indices open side-by-side; the `resizeEvent`/`_on_gen_*` methods are short but the
   *why* (thread affinity, debouncing) is all in the comments — check those still hold if
   you rewrite them.

3. **`helper.py`** — this is the real "what happens when I click X" layer. Read in this
   sub-order, which is also click order: `validator` → `generate`/`DetectionWorker` →
   `preview`/`_trajectory_figsize_for_label`/`apply_trajectory_pixmap` → `genData`. The
   `PrintTee` class at the top is infrastructure or the other three pages — fine to review
   last within this file.

4. **`detector.py`** — the biggest comment-to-code ratio in the codebase (constants block
   alone is ~90 lines of calibration history). Suggested split:
   - Pass A: the constants block — cross-check each numeric constant's comment against
     CLAUDE.md's "Marker detection"/"Standing objective" sections; these are the ones most
     likely to drift out of sync with reality after a repaint/recalibration.
   - Pass B: the detection functions (`remove_duplicate_detections`,
     `fallback_contour_disks`, `resolve_marker`, `detect_disks_color`) — mostly straight
     line-by-line logic, comments explain *why* a gate exists.
   - Pass C: `IDAssigner` — the 4-step `assign()` is the trickiest control flow in the file;
     worth re-reading the class docstring first since it numbers the same 4 steps the code
     comments reference.
   - Pass D: `main()` — ties everything above together frame-by-frame; short on its own,
     mostly a sequencing check once A–C are fresh.

5. **`Pre_process.py`** — read right after `detector.py` since every function here exists
   to be called by something you just read there. `_select_best_blob` is shared by
   `detect_dark_marker_center`'s two passes (strict + relaxed) — read it once, then both
   call sites will make sense without re-deriving the geometry math.

6. **`Post_process.py`** — the other math-heavy file, triggered by `helper.preview()`
   (`visualize_trajectories`) and `helper.genData()` (`build_student_excel`). Suggested split:
   - Pass A: small helpers (`_ensure_sorted`, `_add_meter_cols`, `_unwrap_angle`,
     `_compute_vels`, `_safe_vxvy_mean`, `_safe_median`, `_find_collision_frame`) — quick,
     mostly self-explanatory once you know the CSV schema from `detector.py`'s CSV writer.
   - Pass B: the rotation-fit chain (`_wrap_pi` → `_robust_omega_seed` →
     `_robust_unwrap_and_fit` → `fit_rotation_segments` → `_rotation_segment_summary` →
     `fit_rotation`) — read in exactly this order, each one builds on the last; the
     docstrings on `_sigma_clip_linear_fit` and `fit_rotation_segments` explain the
     "0 outliers ≠ trustworthy" gotcha that's easy to miss just reading the code.
   - Pass C: `_compute_metrics` — the physics. The impulse-direction-normal comment block
     is dense; worth confirming against CLAUDE.md's "Resolved" bug entry on restitution
     before trimming it, since it records a real bug fix, not just style.
   - Pass D: `visualize_trajectories`, `_drop_fallback_rows`, `_fill_theta_gaps_per_disk`,
     `build_student_excel` — the output/export path; `build_student_excel` is the one
     function that ties A–C together into the final `.xlsx`.

7. **`notifier.py`** — shortest file, last in the call chain (`build_student_excel`'s final
   line). Quick read; the interesting design decision (metrics-only, fire-and-forget
   thread) is stated once in the module docstring.

### Cross-cutting things worth a second look while you're in there

- Comment density is very uneven: `detector.py`/`Post_process.py` carry most of the
  project's "why" history (bug writeups, calibration numbers); `Pre_process.py` and
  `notifier.py` are comparatively sparse. If you're normalizing comment style, decide
  up front how much of the *history* (measured numbers, dates, "confirmed 2026-09-XX")
  you want to keep inline vs. push entirely into CLAUDE.md.
- Several magic numbers are calibration constants with a paper trail (detector.py's
  `MARKER_*`/`*_LOWER`/`*_UPPER`, Pre_process's radius/circularity bounds) — worth
  flagging any that *aren't* justified by a comment yet, since CLAUDE.md implies all of
  them should be by now.
- `resource_path` is duplicated verbatim between `app.py` and `helper.py` — not a bug,
  but worth a deliberate "leave as-is" or "extract" decision during the pass rather than
  fixing it incidentally while touching comments nearby.
