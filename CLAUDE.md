# Collision-Study (DEM) — Project Context

> This file is read automatically by Claude Code at the start of sessions in this repo.
> Keep it updated as the project evolves — add new bugs, remove resolved ones, log decisions.
> Keep this file lean: current state and decisions for a fresh session to act on, not a lab
> notebook of how each result was produced. Session-by-session experiment detail belongs in
> conversation history, not here — if a past run's raw numbers aren't load-bearing for a
> current decision or threshold, they don't belong in this file.

## What this is

Python/PyQt6 desktop app that analyzes 2D collisions of two circular pucks on an air table
from video footage, tracking position/orientation/kinematics per frame and exporting
scaled physical metrics (mm, s) to CSV for Discrete Element Method (DEM) validation.

- Disk 0 = Green, Disk 1 = Blue.
- Disk diameter: 70.0 mm (35mm radius, user-confirmed), default mass: 0.0118 kg.
- Disks are painted their full body color (matte, saturated green/blue); the offset marker is
  a black-painted dimple ~20-30mm from disk center, not a separate colored dot — see "Marker
  detection" below. Older footage with a small colored dot on a gray disk body (`Novos
  Videos`/`NL`) is not representative of current runs.
- **Physics**: air table is frictionless (user-confirmed) — angular velocity is expected
  constant between collisions, no torque except during contact.
- **Filming pattern**: real collision videos are a single collision each — two disks
  approach, contact once, separate. Not multi-bounce. Rotation segmentation is exactly two
  segments (before/after) per video, always.
- **Hardware is locked to webcam 1080p@60fps** (see "Lab / lighting history" #6) — the actual
  deployment spec everything is validated against, not a stopgap. Actual webcam fps drifts
  below the nominal 60 — use each video's own measured fps, not an assumed 60.

## Branch note

This branch (`color-thresholding`) removed the entire YOLO-based detection pipeline and its
training assets (`Puck_Training/`, `Puck_Training_Legacy/`, `runs/`, `yolov8n-pose.pt`,
`yolo26n.pt`, `train.py`, `model_acc.py`, `Model_Image_Rel/`) as of 2026-09-19, after
confirming across two real footage sets that it doesn't generalize past the exact gray-body
footage it was trained on (see "Position detection" below for the measured numbers). The
classic small-colored-dot-on-gray-disk marker scheme was removed alongside it, since it only
existed to pair with that old footage. **If YOLO-based detection or the classic marker scheme
is ever needed again** (e.g. a return to unpainted disks), the parent `deepLearning` branch
still has the full implementation, training data, and trained weights intact — don't
reimplement from scratch, check out from there.

## Standing objective

Disks are painted (whole body colored, dimple marker) and position/marker detection are both
color-based (`detect_disks_color` / `resolve_marker`, both in `detector.py`) — no model in the
loop. Current real-footage batches: 3 calibration clips (`Camera Roll\New Disk Tests\`) used to
first tune the color/dimple constants, and a larger batch at `Camera Roll\New Disks\` (10 of
an originally-referenced 18 clips are actually present: `3,4,5,6,7,8,10,17,18.mp4` +
`13 - Trim.mp4`) used to validate end-to-end.

**Current state, as of the 2026-09-19 cleanup session:**
- **Position detection** (`detect_disks_color`): solid. Measured 78-92% both-disk recall
  in-window on the calibration clips.
- **Marker/dimple detection** (`resolve_marker` / `detect_dark_marker_center`): recall, given
  the disk itself was found, is high on most real clips (80-100%). Where it drops, the cause is
  physical, not a threshold bug (see "Marker detection" below): motion blur during the fast
  approach/separation around contact, or the dimple rotating to an arc where it's genuinely
  foreshortened/self-occluded by the disk's own rim from this side-mounted camera's angle.
  **Confirmed 2026-09-19 (user)**: the two clips with the worst dimple contrast (`17`/`18.mp4`)
  were shot with a previous disk batch whose dimple was painted *grey*, not black — lower
  contrast by construction, not a detection failure. Current disks use a black dimple and don't
  have this problem.
- **Excel output always has a theta value per row** (`Post_process._fill_theta_gaps_per_disk`,
  see "Rotation fitting and recovery" below) via per-segment interpolation — the one honest
  exception is a segment with *zero* measured detections at all (nothing to interpolate from),
  which stays blank rather than fabricated.
- **Stale, needs re-measurement**: raw disk *position* recall across a clip's full duration was
  measured at only ~10-40% in the `New Disks` batch as of the 2026-09-19 session (most of a
  clip is before/after the disk is actually in its active throw/collision window). Flagged
  2026-09-23 (user) as no longer trustworthy as a current number — don't cite the 10-40% figure
  as today's state. Decision (2026-09-23, user): re-measure once the app itself is finalized,
  not before — no dedicated regression/recall re-run planned until then.
- **Accepted limitation, not being chased further at 60fps**: sparse both-disk coverage
  specifically *around the collision moment* on some clips (few simultaneous detections right
  when it matters → noisy velocity fit → unreliable e/momentum on those clips). Traced
  (frame-by-frame `IDAssigner` replay) to real fast motion between frames, not ID swaps or a
  tracking bug — position-lock, gated velocity prediction, and the color-first fallback are all
  working as designed. Decision (2026-09-23, user): the pipeline works well enough at current
  60fps for now; a later study phase is expected to move to 120/240fps capture specifically to
  resolve this at the source (more frames across the same fast contact window), rather than
  further tuning shape/color gates under partial occlusion at 60fps.

## Architecture

```
Collision-Study/
├── initializer.py    # Entry point; imports app and calls app.main()
├── app.py             # PyQt6 GUI (file selectors, FPS inputs, process triggers)
├── helper.py          # Bridges GUI calls to backend pipeline
├── detector.py        # Core pipeline: video I/O, detection, ID tracking, CSV export
├── Pre_process.py     # CV utilities (HSV filtering, marker isolation, background estimation)
├── Post_process.py    # CSV -> kinematics/rotation/Excel + collision metrics
└── notifier.py        # Best-effort ntfy.sh push notification on run completion
```

`.env` (gitignored, see `.env.example`) optionally overrides `DEM_WORKSPACE_ROOT`, `NTFY_TOPIC`,
and `DEM_SHOW_RESULTS_SHEET` — loaded by `initializer.py` before anything else imports.

No trained model, no training data, no training scripts — position and marker detection are
both classical HSV/contour CV. See "Branch note" above if that ever needs to change.

### Detection pipeline (`detector.py`)

- **Disk position**: `detect_disks_color()` / `Pre_process.segment_disks_by_color()` — direct
  HSV color-contour on each disk's own paint color, no background image needed for position
  itself. `scale_mm_per_px` comes from the median of the first 8 color-sourced radii
  (`RADIUS_SAMPLE_TARGET`) — don't trust any single frame's radius reading alone.
  Bounds (`COLOR_DISK_MIN/MAX_RADIUS`, `COLOR_DISK_MIN_CIRCULARITY`) are placeholders for this
  webcam's 1080p framing — retune if camera distance changes.
  **Identify-by-exclusion** (`EXCLUSION_LOWER/UPPER`): if the strict per-color search finds
  exactly one disk, tries a looser color net for the other, restricted to outside the confident
  disk's own region — safe because exactly 2 disks/colors exist, so the missing identity is
  unambiguous. Needed because direct glare measurably desaturates the green paint toward grey.
  **Known-color propagation**: `detect_disks_color` tags each detection with the color that
  matched it; `resolve_marker` reuses that instead of re-running an independent bulk-color
  vote, so identity isn't determined twice by two checks that could disagree.
  **If color-thresholding alone ever can't find a disk reliably** (e.g. a shadow/reflection
  desaturating the paint below the calibrated HSV window for a stretch of frames): the fix is
  to lean harder on `fallback_contour_disks()` (below) as a background-subtraction backup for
  exactly the frames color-thresholding misses — not a reversion to pure background-subtraction
  (that inherits the new lab's confirmed glare problem on its own).
- **Fallback**: `fallback_contour_disks()` (background-subtraction contour), only when the
  primary color detector found <2 disks, only within `FALLBACK_SEARCH_RADIUS_PX` of a missing
  disk's *predicted* position (see `IDAssigner.predicted_pos`, not a stale last-seen one),
  radius-gated so glare/reflection blobs can't slip through.
- **`IDAssigner`**: position-lock (within `POSITION_LOCK_GATE_PX`=60px of a tracked ID's last
  position claims it immediately, before color) makes the pipeline robust to a bad single-frame
  color read. Beyond the lock gate, matches against a *predicted* position (last position
  extrapolated by that ID's own last-known velocity × frames-missing), gated at
  `MAX_SPEED_PX_PER_FRAME * gap` — an implausibly-far "only remaining candidate" is left
  unassigned rather than force-matched. `predicted_pos(pid)` is public (used by the contour
  fallback too). Deterministic left-right fallback (step 4) only applies to genuinely
  history-less IDs, never overrides a step-3 rejection.
- **Background estimation** (`Pre_process.estimate_background_median`): median of frames
  sampled from the first `CLEAN_SECONDS`, with a `puck_masker` callback (`main()` passes a
  `detect_disks_color` closure) that excludes detected-puck pixels per sampled frame from the
  median — otherwise a puck already on the table at t=0 gets baked into the "background."
  Falls back to the plain median where no clean sample exists anywhere for a pixel (honest
  limit, not fixable without different data). Only backs the contour fallback now — position
  detection itself doesn't need it.

### Marker detection (`resolve_marker` in `detector.py`)

Disk *identity* comes from the disk body's bulk color (`Pre_process.classify_disk_bulk_color`,
a majority vote over the whole disk interior, ≥15% share required), and the *marker* comes
from the darkest compact region within that now-reliably-colored disk
(`Pre_process.detect_dark_marker_center`, threshold relative to that disk's own median V).
Both share crop/geometry/contour-selection logic via `Pre_process._select_best_blob`.

- `GREEN_LOWER/UPPER`, `BLUE_LOWER/UPPER`: calibrated from a real survey (95 green-disk /
  251 blue-disk body-color samples, p1/p50/p99 percentiles). Blue's real saturation runs
  hotter than green's (up to S≈248 vs green comfortably inside a narrower band).
- `MARKER_MIN_AREA_FRAC`/`MARKER_MIN_CIRCULARITY`/`MARKER_MAX_CIRCULARITY`: shape gates for
  the dimple contour, calibrated against ~94/250 real dimple samples (min area frac p1
  ≈0.016-0.019, min circularity p1 ≈0.70-0.73, max circularity p99 ≈0.91-0.92).
- `MARKER_DARK_VALUE_FRAC` (0.55) / `MARKER_DARK_VALUE_FRAC_GREEN` (0.72): the dimple threshold
  is relative to *that disk's own* median V, but green's painted body measures far darker
  overall than blue's — the same relative threshold that reliably isolates blue's dimple
  (ratio ~0.36-0.48) almost never triggers on darker green (ratio ~0.6-0.65). Green gets its
  own retuned constant, chosen via a real-footage sweep (0.55→14%, 0.65→50%, 0.70→93%,
  0.72→100% green-marker recall) and visually confirmed landing on the real dimple. Originally
  flagged as a software mitigation pending a brighter/lighter green repaint — confirmed
  2026-09-23 (user) that the current green paint is final and no repaint is planned, so this
  constant is the permanent fix, not a stopgap. Left as a separate constant from
  `MARKER_DARK_VALUE_FRAC` rather than merged, since the two paints' V-headroom genuinely
  differs.
- `MARKER_RELAX_FRAC_DELTA` (0.10) / `MARKER_MAX_AREA_FRAC` (0.12): a handful of frames sit
  right at the edge of the calibrated dark-value threshold with a genuinely darker-than-
  background but marginally-subtle dimple. `detect_dark_marker_center` gets one bounded
  relaxed retry for exactly these marginal misses (`relax_frac_delta`), gated by a max-area cap
  (`max_area`) so the relaxed pass can't mistake a frame where the *whole disk* dipped darker
  (motion blur / passing shadow / exposure dip) for the marker — a relaxed threshold with no
  cap was measured growing the "dark" region from 0px to >1000px (near-disk-sized) on exactly
  such a frame, vs. a real dimple's ~100-300px. Verified on the real `New Disks` batch: blue
  recall on 3 clips jumped 52-77% → 95-100% with no regressions anywhere.
- `EXCLUSION_LOWER/UPPER`: see "Identify-by-exclusion" above — deliberately much looser on
  saturation than either real color's calibrated window, but only ever tried when the strict
  search found exactly one of the two disks, so it can't manufacture a second disk out of noise.
- **Root cause of remaining marker misses is physical, not tunable**: motion blur near contact,
  or the dimple rotating to an arc self-occluded by the disk's own rim from this side camera's
  angle (confirmed visually: a disk crop can show *no* visible dark dimple at all for 15+
  consecutive frames, not just a low-contrast one, then a clearly visible one reappears later).
  Confirmed 2026-09-19: the worst-affected clips in the `New Disks` batch (`17`/`18.mp4`) were
  shot with an earlier disk batch's grey (not black) dimple paint — lower contrast by
  construction. Current black-dimple disks don't have this problem. The actual mitigation for
  the frames a dimple genuinely isn't visible is interpolation (see "Rotation fitting and
  recovery" below), not further threshold tuning.
- **Paint spec**: matte/flat finish, spray paint formulated for plastic, saturated green/blue
  mid-tones, marker dimple painted black (not grey, not left bare).

### Rotation fitting and recovery (`Post_process.py`)

Segments each disk's timeline at the collision frame (`Post_process._find_collision_frame`)
into "before"/"after" (never fit across the boundary — contact torque means ω isn't constant
there) and robustly fits angular velocity per segment:

- **`Post_process.fit_rotation_segments`** (per-disk) / **`fit_rotation`** (two-disk,
  shared collision frame): unwraps + fits θ vs. frame via `_robust_unwrap_and_fit`. A naive
  "sequential `np.unwrap` then sigma-clip" pipeline is NOT safe — a single bad value near the
  ±180° branch cut can flip which 360° branch sequential unwrap locks onto for every later
  sample, so sigma-clip never sees an outlier, it sees a uniformly-shifted trend (reproduced:
  one bad point flipped a fitted ω's sign). Fixed by branching each sample against a robust
  linear *prediction* (`_robust_omega_seed`, seeded from wrapped pairwise slopes — never runs
  a global sequential unwrap), refined over a few rounds with the sigma-clip fit.
  Also NaN-safe (a prior version's `np.unwrap` call would poison every value after the first
  gap — `np.unwrap` does not skip NaN).
  Output columns per row: `theta_unwrapped_deg`, `rotation_segment`, `theta_trend_consistent`
  (True/False/NaN), `omega_fit_deg_per_frame`, `theta_fit_intercept_deg`,
  `omega_fit_residual_std_deg`.
  **Critical gotcha: "0 outliers" does NOT mean "trustworthy fit."** Sigma-clipping only
  rejects points relative to the fit's *own* noise floor — if most of a segment's data is
  genuinely poor, that floor inflates and nothing looks like an outlier. Measured on real
  footage: one segment reported 0/68 outliers with ω matching the expected ~1°/frame, yet had
  a residual std of ~79° and its fitted ω swung wildly (-1.0 to +1.86 deg/frame) under random
  holdout of its own "inliers." A *different* segment with 51 raw outliers had a residual std
  of only ~1.94° once those were excluded — far more trustworthy despite looking "messier."
  **Always check `omega_fit_residual_std_deg` directly, never infer precision from outlier
  count alone.**
- `_compute_metrics` (restitution/momentum/energy) uses the RANSAC-fitted `omega_fit_deg_per_frame`
  for the rotational KE term when available, falling back to the raw per-frame `omega_deg_s`
  median for segments too sparse to fit at all.
- `_compute_vels` divides by actual elapsed frames (`frame.diff()`), not a hardcoded 1 — a
  disk missing from a frame gets no row at all (not a NaN placeholder), so consecutive rows
  can legitimately be more than 1 frame apart.
- **`_fill_theta_gaps_per_disk`** (called from `build_student_excel`): guarantees a `theta_deg`
  value on every exported row. Per disk, per rotation segment (before/after the collision frame
  — never across it), linearly interpolates missing `theta_deg` against `frame` from that
  disk's own nearest measured neighbors. This is more than a smoothing convenience — on this
  frictionless table, angular velocity is genuinely constant between collisions, so theta vs.
  frame really is linear within a segment, meaning interpolation recovers the true intermediate
  value. A gap at a segment's leading/trailing edge (no earlier/later measurement to
  interpolate between) holds flat at the nearest available value instead of extrapolating past
  the last real reading. The single collision-frame row (excluded from both segments, since
  omega isn't assumed constant during contact) can't be modeled at all — if missing, it's
  carried from the adjacent segment instead of left blank, tagged `collision_nearest`. Adds a
  `theta_source` column to the Raw_Data sheet (`measured`/`interpolated`/`collision_nearest`/
  `None` — `None` only when an entire segment has zero measured theta values at all, i.e.
  nothing to interpolate from; a real but rare limit on badly-occluded footage, not silently
  papered over).

### Notifier (`notifier.py`)

Best-effort ntfy.sh push notification when a run finishes, called from the end of
`build_student_excel`. Answers the "Idea, not designed yet" item from Known bugs above — the
professor (user) wants results checkable from a phone right after a run, to catch a bad run and
have the student redo it on the spot rather than discovering it later; this is mandatory for
them, not an opt-in feature, so there's deliberately no per-run GUI toggle (only the
`NTFY_TOPIC` env var gates it, machine-wide).

- **Metrics only, never raw data or the file itself** (user, 2026-09-23): the notification body
  is the Results-sheet rows (e, momentum error, energy drop, collision_gap_mm/warning, theta
  interpolation %) plus a small Raw_Data row-count summary — never the per-frame data, never an
  attached `.xlsx`.
- **Runs on a background thread**: `notify_run_complete` spins up a daemon `threading.Thread`
  for the actual `requests.post` instead of calling it inline — `build_student_excel` runs on
  the GUI thread (via `helper.genData()`), so a synchronous network call there would block the
  UI. Fire-and-forget is safe here since nothing needs the result and every failure path is
  already swallowed (no network, ntfy.sh down, etc. must never break the actual analysis run).
- **`DEM_SHOW_RESULTS_SHEET`** (see `.env.example`): metrics are always computed (needed for the
  notification regardless), but the Results sheet is only written into the delivered `.xlsx`
  when this is set to `1` — default is left out, since students don't need it there and the
  professor already gets the numbers via the notification.

## Lab / lighting history — conclusions for the next shoot

1. New lab's overhead LED bars cause glare that broke classical detection on the old gray-body
   footage/marker scheme (confirmed root cause, not camera choice — webcam and phone camera
   both failed under the same lighting).
2. Removing the direct-overhead lights (`Camera Roll/NL/`) measurably helped marker recall at
   60fps (71-73% vs ~44-56% lit) on that old scheme. Not re-verified against the current
   painted-disk scheme.
3. 240fps's blur-reduction benefit (shorter shutter, less motion blur during approach/
   separation) is real and separate from rotation sampling (which is oversampled even at
   60fps). The tradeoff is exposure — the available bright light flickers above 60fps.
   **Superseded by #6 below** — moot now that the deliverable is locked to a 60fps webcam.
4. **Repositioning to the other side of the table**: tried once (`Other_Side.mp4`). Tradeoff
   observed by eye: noticeably more shadow from that side. A same-session, per-clip color-blob
   disk count found more disk-body detections in `Other_Side` (70 green / 151 blue) than either
   `Previous_Side_Light` (25 / 49) or `Previous_Side_No_Light` (0 / 51) — but this is **not a
   controlled comparison** (each clip is a different throw/trajectory, so more time on-camera
   confounds the count) and shouldn't be read as "shadow beats glare" without a same-trajectory
   repeat. **Decision (2026-09-23, user): discontinued.** Filming stays on the regular side
   documented throughout the rest of this file — `Other_Side` is not an option going forward.
5. **4K resolution**: would help marker precision in principle, but **moot — superseded by
   #6**, the deployment camera is a 1080p webcam with no 4K mode.
6. **Hardware decision: webcam-only, no external hardware.** Professor requires the project not
   depend on external hardware (no dedicated camera/phone purchase for the pipeline itself).
   Deployment target is fixed at **1080p @ 60fps via webcam** — this is not a stopgap, it's the
   actual spec to validate and tune against going forward. A phone may still be used later for
   one-off calibration/reference footage, but the shipped pipeline must work on webcam
   1080p60fps footage.

## Known bugs / open issues

1. Raw disk *position* recall across a clip's full duration — see "Standing objective" above,
   stale numbers, needs re-measurement.
2. **Idea, not designed yet**: some kind of lightweight server/notification setup so results
   (e, momentum error, energy drop, collision_gap_mm) can be checked from a phone shortly after
   a trial run, so a bad run can be flagged for the student to redo on the spot rather than
   discovered later. Since built as `notifier.py` — see "Notifier" section below for its actual
   scope and remaining gaps.

**Resolved:**

- **`estimate_background_median`'s puck mask only protects detected-puck pixels.** A puck
  sitting somewhere the detector doesn't detect at all during the sample window wouldn't be
  excluded from the background median. Closed as a non-issue (2026-09-23, user): in practice
  disks only enter frame 2-3 seconds in, well after `CLEAN_SECONDS` sampling completes, so this
  edge case doesn't occur with the current filming setup.
- **`Other_Side`-style clips requiring manual trimming.** Moot as of 2026-09-23 (user): that
  camera position is no longer used for filming going forward (see "Lab / lighting history" #4)
  — nothing to trim if nothing's shot there.
- **56-60fps undersampled/missed collisions had no automated flag.** `collision_gap_mm`
  (`_compute_metrics`'s diagnostic) existed but nothing acted on it. Policy set 2026-09-23
  (user): a `collision_gap_mm` greater than one disk radius prints a `[WARN]` and sets
  `collision_gap_warning=True` in the metrics dict (also a row in the Results sheet) — still
  doesn't distinguish "real but undersampled" from "no collision happened," just surfaces the
  clips worth a second look instead of silently trusting every fitted `e`/momentum value.
- **`collision_gap_mm` unit-mismatch bug.** `_compute_metrics` (`Post_process.py`) received
  `radius` in mm (the GUI field is labeled mm) but treated it as meters in two places: the
  `collision_gap_mm` diagnostic subtracted the raw mm sum from a meter-scale recorded distance
  before re-multiplying by 1000, and `RADIUS_M` (feeding `INERTIA` for the rotational-KE term)
  used the raw mm value as meters — inflating rotational KE by ~1e6x whenever a segment's
  fitted omega was nonzero. Fix: convert `radius` to meters once at the top of
  `_compute_metrics` (`radius_m`), used everywhere downstream.
- **Restitution normal derived from position instead of velocity.** `_compute_metrics` used to
  derive the collision normal from disk *positions* at the single recorded "collision frame"
  (closest recorded center-to-center distance) — fragile whenever the true closest approach
  fell in a gap between detected frames (measured: a recorded 87mm minimum against an expected
  ~70mm true contact distance produced an unphysical e=1.46). Fix: derive the normal from each
  disk's own measured velocity change (impulse direction) instead — on a frictionless table the
  contact force has no tangential component, so each disk's Δv is *exactly* along the true line
  of centers at the instant of contact, regardless of whether that instant was ever sampled.
- **Green marker (dimple) detection.** Root cause: the dark-value threshold is relative to that
  disk's own median V, but green's painted body measures far darker overall than blue's, so the
  same relative threshold that reliably isolates blue's dimple almost never triggers on green.
  Fixed via `MARKER_DARK_VALUE_FRAC_GREEN` (see "Marker detection" above) — not the durable
  fix (a brighter green paint is), but resolves it for the current paint.
- **Low theta/rotation coverage on real footage, diagnosed and addressed 2026-09-19** — see
  "Standing objective" and "Marker detection" above for the two physical causes found (motion
  blur, self-occlusion), the one real threshold gap that was fixed (`MARKER_RELAX_FRAC_DELTA`/
  `MARKER_MAX_AREA_FRAC`), and the interpolation guarantee added to the Excel export
  (`_fill_theta_gaps_per_disk`).

## Reference: local test footage

- `Camera Roll\New Disk Tests\` — 3 webcam clips (`Previous_Side_Light.mp4`,
  `Previous_Side_No_Light.mp4`, `Other_Side.mp4`, ~1080p@56-57fps) used to first calibrate the
  color/dimple constants on real painted-disk footage.
- `Camera Roll\New Disks\` — larger real batch, 10 of an originally-referenced 18 clips present
  as of the 2026-09-19 cleanup (`3,4,5,6,7,8,10,17,18.mp4` + `13 - Trim.mp4`), not yet in repo.
  `17`/`18.mp4` used an earlier grey-dimple disk batch (lower marker contrast by construction —
  see "Marker detection"), not representative of the current black-dimple disks.
- `Camera Roll\NL\` / `Camera Roll\Novos Videos\` — old gray-body-disk footage (no whole-disk
  paint, small colored-dot marker). Not representative of current runs; kept only as lighting-
  history context (see "Lab / lighting history").
- `Videos/` in the repo itself is empty — no test footage there.

## Long Term Issues (not critical)

- ~~Add a loading/progress indicator between hitting "generate" and the preview being ready.~~
  **Done** — `hp.generate()` now runs `detector.main()` on a background `QThread`
  (`DetectionWorker` in `helper.py`) instead of blocking the GUI thread, reporting progress via
  a `progressGen` (`QProgressBar`, `gui.ui`, Page 5) that fills 0-100% as frames process, then
  shows "Done" and enables Preview. `detector.main()` gained an optional `progress_callback`
  parameter for this (no Qt dependency added there). **Threading gotcha worth remembering**:
  connect worker-thread signals to real bound methods of a `QObject` (added
  `_on_gen_progress`/`_on_gen_finished`/`_on_gen_failed` on `MainWindow`), not bare
  lambdas/functions — Qt can only auto-detect a signal connection's thread affinity (and
  therefore safely queue the call onto the GUI thread) when the slot is a QObject's own bound
  method; a plain lambda has no owning QObject to key off and would otherwise execute directly
  on the worker thread, unsafe for touching any widget. Verified with a real end-to-end GUI run
  (driven from a script, no manual clicking): confirmed non-blocking return, confirmed the
  progress value visibly climbs through every integer percentage rather than jumping, and
  confirmed correct completion state.

## Working preferences

- User is an Aerospace Engineering student, comfortable with Python/CV concepts — direct
  technical explanations over hand-holding.
- Prefers full code/analysis upfront, makes editorial decisions independently.
- Reasonable to move fast on changes clearly in service of the standing objective above
  without re-confirming each one, but this isn't blanket authorization for unrelated or
  destructive actions — normal judgment on risk/reversibility still applies.
- Values honest reporting over optimistic framing — e.g. explicitly asked whether a "0
  outliers" fit result could be trusted, which surfaced the residual-std gap above; prefer
  surfacing a real limitation/negative result clearly over a rosier summary.
