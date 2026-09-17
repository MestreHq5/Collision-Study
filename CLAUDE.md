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

- Disk 0 = Green marker, Disk 1 = Blue marker
- Disk diameter: 70.0 mm (35mm radius, user-confirmed), default mass: 0.0118 kg
- Offset marker sits ~20-30mm from disk center, circular, colored blue or green
- Disk **bodies** are gray/slate — only the small offset marker dot is colored (current,
  pre-repaint footage only — see "Marker detection: two schemes" below).
- **Physics**: air table is frictionless (user-confirmed) — angular velocity is expected
  constant between collisions, no torque except during contact.
- **Filming pattern**: real collision videos are a single collision each — two disks
  approach, contact once, separate. Not multi-bounce. Rotation segmentation is exactly two
  segments (before/after) per video, always.
- `Camera Roll/Novos Videos/` clips were recorded to build the deep-learning dataset, not as
  real collision-study runs — expect varied/non-representative trajectories there, unlike real
  single-collision footage.

## Standing objective

**Disks are now repainted** (whole disk colored blue/green, marker is a black-or-grey dimple —
see "Marker detection: two schemes" below), and 3 real webcam test clips exist as of
2026-09-17 (`C:\Users\gonca\Pictures\Camera Roll\New Disk Tests\`: `Previous_Side_Light.mp4`,
`Previous_Side_No_Light.mp4`, `Other_Side.mp4`, ~1080p@56-57fps — actual webcam fps drifts
below the nominal 60, use each video's own measured fps, not an assumed 60).

**Status as of 2026-09-17 session end — real progress on a bigger sample, still not final:**
1. **Marker/color logic (flipped scheme): retuned against real data.** `MARKER_SCHEME =
   "flipped"`, constants retuned against a real calibration survey — see "Marker detection:
   two schemes" for the numbers. Only 3 clips / ~1300 frames, smaller than the classic
   scheme's 580-sample survey — good first pass, not final.
2. **Position detection: pivoted from YOLO to color-thresholding** (`color-thresholding`
   branch, `detect_disks_color()` / `Pre_process.segment_disks_by_color()`, no model — `train-5`
   YOLO confirmed not to generalize to painted disks, see Model section). Two added
   refinements this session (both user-requested):
   - **Identify-by-exclusion** (`FLIPPED_EXCLUSION_LOWER/UPPER`): if the strict per-color
     search finds exactly one disk, tries a looser color net for the other, restricted to
     outside the confident disk's own region — safe because exactly 2 disks/colors exist, so
     the missing identity is unambiguous. Confirmed real and needed: direct glare measurably
     desaturates this specific green paint toward grey (user-observed, then confirmed in
     data — green used this fallback far more often than blue across the 18-clip batch below).
   - **Known-color propagation**: `detect_disks_color` now tags each detection with the color
     that matched it; `resolve_marker_flipped_scheme` reuses that instead of re-running an
     independent bulk-color vote, so identity isn't determined twice by two checks that could
     disagree.
3. **Batch-tested end-to-end against 18 new real clips** (`C:\Users\gonca\Pictures\Camera
   Roll\New Disks\1.mp4`-`18.mp4`, not yet in repo) — full detection + `build_student_excel`
   physics, not just recall:
   - **~9-10 of 18 clips produced plausible collision metrics** (e roughly 0.6-1.05,
     momentum error mostly <10%; clip 4 was a partial exception — momentum error 5.5% but an
     unphysical e=1.46, not yet explained). This is a real base rate on a real sample, not
     the single lucky clip from earlier the same day.
   - **The other ~8 clips failed on sparse both-disk coverage around the collision moment
     (few simultaneous detections → noisy velocity fit → nonsense e/momentum), not on
     identity/tracking bugs.** Specifically traced this (user asked for a continuity check):
     replayed `IDAssigner.assign()` frame-by-frame on the two worst clips and confirmed large
     position deltas are real fast motion between consecutive frames (~5 m/s, physically
     plausible for a hand-thrown puck), not ID swaps — position-lock, gated velocity
     prediction, and the color-first fallback are all functioning as designed. **Root cause of
     the sparse-coverage failures is still open** — didn't get to why detection density drops
     specifically near contact on those clips (motion blur at contact? gates too strict under
     partial occlusion? something else) — that's the actual next step, not further
     ID-assignment work.
4. **Still not validated**: the marker/dimple/rotation side of the flipped scheme (theta,
   omega_fit) — only checked via the static calibration survey (HSV/shape percentiles), not
   the classic scheme's stationary-disk real-motion check (angle std / flip-flop test) that
   caught the classic scheme's known marker bug. YOLO annotation/retraining remains
   deprioritized, not abandoned, as the fallback if color-thresholding's coverage problem
   turns out not to be fixable.

**Hardware is locked to webcam 1080p@60fps** (see "Lab / lighting history" #6) — that's the
deployment spec to validate everything against going forward, not a stopgap. `Novos Videos`/
`NL` remain old-appearance dataset-building/test footage, not representative of current
collision runs.

## Architecture

```
Collision-Study/
├── initializer.py    # Entry point; imports app and calls app.main()
├── app.py             # PyQt6 GUI (file selectors, FPS inputs, process triggers)
├── helper.py          # Bridges GUI calls to backend pipeline
├── detector.py        # Core pipeline: video I/O, detection, ID tracking, CSV export,
│                       # rotation-recovery post-processing pass
├── Pre_process.py     # CV utilities (HSV filtering, marker isolation, background estimation)
├── Post_process.py    # CSV -> kinematics/rotation/Excel + collision metrics
├── train.py           # Retrains the YOLO Pose model from Puck_Training/ (see Model section)
└── runs/pose/train-5/weights/best.pt   # Fine-tuned YOLO Pose model (deployed)
```

**Two active branches as of 2026-09-17**: `deepLearning` (YOLO-based position detection,
prior main line) and **`color-thresholding`** (current work — HSV color-contour position
detection, branched off `deepLearning`; see "Disk position" below and ToDo.md section 5 for
why). `main` and `noLiveFeed` are older, not part of current work. All of this session's
changes (both branches' worth of work — the flipped-scheme retune plus the new
color-thresholding detector) are **uncommitted** on `color-thresholding` as of session end —
`git status` shows `CLAUDE.md`, `Pre_process.py`, `detector.py`, `ToDo.md` modified. Nothing
lost (it's all on disk), just not yet committed — do that deliberately next session rather
than assuming it already happened.

### Detection pipeline (`detector.py`)

- **Disk position — two branches, split 2026-09-17 after real repainted-disk footage exposed a
  YOLO domain-shift failure (see Model section and ToDo.md section 5 for the measured numbers):**
  - **`color-thresholding` branch (this one)**: `detect_disks_color()` / `Pre_process.
    segment_disks_by_color()` — direct HSV color-contour on each disk's own paint color, no
    model, no background image needed for position itself. Measured 78-92% both-disk recall
    in-window on real footage (vs. YOLO's near-total failure on the same clips) and, on an
    18-clip real batch, ~9-10/18 produced physically plausible collision metrics end-to-end
    (see Standing objective for the full breakdown, including the identify-by-exclusion and
    known-color-propagation additions and the still-open sparse-coverage failure mode).
    `scale_mm_per_px` comes from the median of the first 8 color-sourced radii (same
    `RADIUS_SAMPLE_TARGET` mechanism, same "don't trust one frame's radius" rationale as
    YOLO's bbox). Bounds (`COLOR_DISK_MIN/MAX_RADIUS`,
    `COLOR_DISK_MIN_CIRCULARITY`) are placeholders for this webcam's 1080p framing — retune if
    camera distance changes.
    **If this hits a real problem** (a footage condition where color-thresholding alone can't
    find a disk reliably — e.g. a shadow or reflection desaturating the paint below the
    calibrated HSV window for a stretch of frames): the fix is a **hybrid**, not a full
    reversion — reuse `fallback_contour_disks()` (below) more aggressively as a background-
    subtraction backup for exactly the frames color-thresholding misses, the same pattern
    already used for YOLO's own gaps. Don't rebuild this branch as pure background-subtraction
    (that's `main`'s old approach and it inherits the new lab's confirmed glare problem on its
    own) — the color signal is the reliable part now that the whole disk is painted; background
    subtraction is only ever the patch for the frames it can't reach.
  - **`deepLearning` branch (prior)**: YOLO Pose (single class `puck`, 2 keypoints
    `[center, marker]`), `detect_disks_yolo()`, `conf=0.10`, `imgsz=1280` — solid/near-perfect
    on the *old* gray-body disks (see Model section), but confirmed not to generalize to
    painted ones. Kept intact and switchable back to if `color-thresholding` doesn't hold up
    on a broader footage set. **Treat bbox radius as noisy, not ground truth** (measured cases
    underestimating the true disk by >3x) — never build tight geometry off a single frame's
    bbox.
- **Fallback**: `fallback_contour_disks()` (background-subtraction contour), only when the
  primary detector (YOLO or color, per branch) found <2 disks, only within
  `FALLBACK_SEARCH_RADIUS_PX` of a missing disk's *predicted* position (see
  `IDAssigner.predicted_pos`, not a stale last-seen one), radius-gated so glare/reflection
  blobs can't slip through.
- **`IDAssigner`**: position-lock (within `POSITION_LOCK_GATE_PX`=60px of a tracked ID's last
  position claims it immediately, before color) makes the pipeline robust to a bad single-frame
  color read. Beyond the lock gate, matches against a *predicted* position (last position
  extrapolated by that ID's own last-known velocity × frames-missing), gated at
  `MAX_SPEED_PX_PER_FRAME * gap` — an implausibly-far "only remaining candidate" is left
  unassigned rather than force-matched. `predicted_pos(pid)` is public (used by the contour
  fallback too). Deterministic left-right fallback (step 4) only applies to genuinely
  history-less IDs, never overrides a step-3 rejection.
- **Background estimation** (`Pre_process.estimate_background_median`): median of frames
  sampled from the first `CLEAN_SECONDS`, with an optional `puck_masker` callback (`main()`
  passes a YOLO-detection closure) that excludes detected-puck pixels per sampled frame from
  the median — otherwise a puck already on the table at t=0 gets baked into the "background."
  Falls back to the plain median where no clean sample exists anywhere for a pixel (honest
  limit, not fixable without different data).

### Marker detection: two schemes

`detector.MARKER_SCHEME` selects which runs — **`"flipped"` is the default as of 2026-09-17**
(repainted-disk footage now exists and calibrated it; see below). `"classic"` remains for the
old gray-body footage (`Novos Videos`/`NL`).

- **`"classic"`** (current, unpainted footage — small colored dot on a gray disk body):
  `resolve_marker_color()` / `Pre_process.detect_marker_center()`. Searches a padded crop
  (`MARKER_SEARCH_PAD_FACTOR=3.5`), excluding a small central disc (`MARKER_DIST_MIN_FRAC=0.3`)
  and — once `scale_mm_per_px` is known — hard-bounded to the disk's own physical 35mm radius
  (`DISK_RADIUS_MM`), not the old unbounded search. Picks the **largest contour that passes
  the shape gate** (`MARKER_MIN_AREA_FRAC`, `MARKER_MIN_CIRCULARITY=0.62`,
  `MARKER_MAX_CIRCULARITY=0.90`), not simply the largest contour — a real marker can be fused
  with background by mask cleanup into one large blob that fails the shape gate while the real
  small round blob sits right next to it unconsidered. CLAHE tile grid and morphological
  kernel scale to crop/disk size (fixed pixel constants break across different object scales).
  Calibrated from a broad survey (580 marker samples, all 28 `Novos Videos` clips).
  **Known limitation, not fixable by more tuning on this footage**: the disk material is
  near-black (HSV hue/saturation inherently unstable at low value), there's a second unpainted
  dimple next to the real marker that sometimes reads as a plausible false match, and overhead
  glare crosses the disk in many frames — confirmed via a controlled real-footage test (a
  stationary disk, so any detected marker movement is pure noise): even after the physical
  radius bound, marker angle std stayed ~100-122° and `marker_color` still flip-flopped
  green/blue frame-to-frame. This is why the repaint is the real fix, not further classical-CV
  work on current material.
- **`"flipped"`** (current, repainted disks — whole disk colored, marker = black/grey dimple):
  `resolve_marker_flipped_scheme()` / `Pre_process.classify_disk_bulk_color()` (disk identity
  via majority-vote color match over the whole disk interior, ≥15% share required) +
  `Pre_process.detect_dark_marker_center()` (marker = darkest compact blob within the disk,
  threshold relative to that disk's own median V). Shares crop/geometry/contour-selection
  logic with the classic path via `Pre_process._select_best_blob`.
  **Constants retuned 2026-09-17** against a first real calibration survey (3 webcam clips,
  ~1300 frames, classical color-blob detection independent of YOLO — see Model section for why
  YOLO itself couldn't be used for this survey): 95 green-disk / 251 blue-disk body-color
  samples, ~94/250 dimple samples, p1/p50/p99 percentiles (same methodology as the classic
  scheme's 580-sample survey, but a smaller first pass — worth widening later, same as classic
  scheme's constants were revised more than once).
  - `FLIPPED_GREEN_LOWER/UPPER`, `FLIPPED_BLUE_LOWER/UPPER`: tightened from the inherited
    classic-scheme bounds to the real measured (H,S,V) clusters + margin. **Blue paint's real
    saturation runs far hotter than the old assumption** — measured up to S≈248, while the
    inherited `BLUE_UPPER` capped S at 175 and would have silently clipped most of the real
    blue disk out of the bulk-color vote. Green's real range sat comfortably inside the old
    bounds; tightened anyway now that real data exists.
  - `FLIPPED_MARKER_MAX_CIRCULARITY`: raised 0.90 → 0.94 — measured real dimple circularity
    p99 ≈ 0.91-0.92, so the inherited 0.90 ceiling would have rejected ~1% of real dimples for
    being "too circular."
  - `FLIPPED_MARKER_MIN_AREA_FRAC`: nudged 0.015 → 0.012 for margin below the measured p1
    (≈0.016-0.019).
  - `FLIPPED_MARKER_DARK_VALUE_FRAC` (0.55) and `FLIPPED_MARKER_MIN_CIRCULARITY` (0.62,
    inherited): measured real dimple-V/body-V ratio (p50 ≈0.37-0.46, p99 ≈0.61-0.63) and real
    circularity floor (p1 ≈0.70-0.73) both landed safely inside these as-is — no change needed.
  **Paint spec that produced this footage**: matte/flat finish, spray paint formulated for
  plastic, saturated green/blue mid-tones, marker dimple painted black/grey (not left bare),
  other dimple filled to match the body. Visually confirmed in the footage: no obvious glare on
  the disk bodies themselves, dimple clearly visible by eye — the paint job looks like it did
  its job for the marker-detection side of things.

### Rotation fitting and recovery (`Post_process.py` + `detector.py`)

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
- **`detector.fill_rotation_gaps`** (per-disk) / **`recover_and_fill_rotation`** (two-disk CSV
  entry point, writes a *separate* enriched CSV, never overwrites the original): for frames
  missing or flagged trend-inconsistent, predicts the marker's position from the segment fit
  and this disk's own measured marker-offset radius. Stage 1 (needs an open `cv2.VideoCapture`,
  optional): real, narrow, high-sensitivity confirmation search on the actual video frame at
  the predicted position, in this disk's already-known color (no green/blue ambiguity, unlike
  the live per-frame detector) — safe to search narrowly here specifically because location is
  already physics-constrained. Stage 2 (fallback, or whenever no video access): pure predicted
  value, no confirmation. Writes `theta_source` (`measured`/`recovered`/`interpolated`/`None`).
  Gated by `detector.MAX_FIT_RESIDUAL_STD_DEG` (45°, explicit placeholder judgment call, not a
  calibrated cutoff) — refuses to recover/interpolate against a segment whose fit isn't
  precise enough to trust, leaving `theta_source=None` rather than a confident-looking but
  possibly-random value. **Validated on real held-out footage** (held out real detections,
  compared recovered/interpolated values against the true held-out ones): on a trustworthy
  segment (residual std ~2°), recovery averaged 5.0° error, interpolation 1.3° error; on an
  untrustworthy one (residual std ~79°), the gate correctly refuses instead of the ~52°-average
  garbage it would otherwise produce.
  **Not yet wired into the GUI/`app.py`/`helper.py` flow** — `recover_and_fill_rotation` is a
  standalone function, called manually or from a script today, not part of a normal
  detect-then-export run. Wiring it in (and deciding whether/how `theta_source` should feed
  `build_student_excel`'s output) is unstarted follow-up work, not done.
- `_compute_metrics` (restitution/momentum/energy) uses the RANSAC-fitted `omega_fit_deg_per_frame`
  for the rotational KE term when available, falling back to the raw per-frame `omega_deg_s`
  median for segments too sparse to fit at all.
- `_compute_vels` divides by actual elapsed frames (`frame.diff()`), not a hardcoded 1 — a
  disk missing from a frame gets no row at all (not a NaN placeholder), so consecutive rows
  can legitimately be more than 1 frame apart.

## Model (YOLO Pose)

- **Deployed**: `runs/pose/train-5/weights/best.pt`, imgsz=1280, single class `puck`,
  `kpt_shape=[2,3]` (`[center, marker]`). Converged, not data-starved (mAP plateaus early;
  more images of the same kind won't move it) — **but this was measured entirely on gray-body
  pre-repaint disks; `Puck_Training/` contains zero painted-disk frames.**
- **Position/box detection is solid and validated — on the OLD gray-body appearance only.**
  **Confirmed 2026-09-17 to NOT generalize to repainted disks**: run against 3 real webcam
  clips of the new painted disks (~1300 frames total), `detect_disks_yolo()` returned boxes
  4-5x undersized (radius ~10-14px vs a real measured ~40-66px, via an independent classical
  color-blob measurement), at confidence ~0.05-0.25 — mostly below the pipeline's own
  `YOLO_CONF=0.10` operating threshold — with only ~5-26% frame recall, and only 0-12 frames
  per clip had *both* disks detected simultaneously (required for tracking). This is a real,
  measured regression, not a hypothetical risk: **new annotated training data of the painted
  disks is required before the pipeline works end-to-end on this footage** — retuning the
  flipped marker-scheme constants (done, see below) was necessary but not sufficient. Once
  annotated frames exist, fine-tune from `train-5`'s weights rather than retraining from
  scratch (position/shape detection fundamentals shouldn't need to be relearned, only the new
  color appearance).
- **The marker keypoint is unreliable** (~44% land on a non-marker specular highlight, measured
  on the old gray-body footage) and is **not used** by the pipeline — marker localization is
  100% classical CV, independent of this keypoint. Irrelevant to the domain-shift problem above
  (that's the box/center detection, not this keypoint).
- **Trust the end-to-end pipeline test over isolated pose mAP** — shown twice not to predict
  real performance: a higher-mAP checkpoint (`240fps_trial_02-2`) didn't beat train-5
  end-to-end, and a keypoint-sigma-reweighted retrain (`marker_weighted`, prioritizing the
  marker keypoint in the loss) made the keypoint's own accuracy *worse*, not better. Neither
  switched. Not conclusively disproven (real run-to-run variance exists, one seed each) but not
  worth pursuing further given the marker keypoint isn't used anyway.

## deepLearning vs. classical OpenCV contour

Settled — **keep YOLO for disk position/tracking**. Classical contour detection failed
specifically because of glare under the new lab's lighting, independent of blur/shutter; YOLO
has since been validated near-perfect under the same conditions. Marker color/position has
always been 100% classical CV regardless (the marker keypoint is unused) — the marker's
struggle is that same glare problem hitting classical detection on the marker instead of the
whole disk.

## Lab / lighting history — conclusions for the next shoot

1. New lab's overhead LED bars cause glare that broke classical detection (confirmed root
   cause, not camera choice — webcam and phone camera both failed under the same lighting).
2. Removing the direct-overhead lights (`Camera Roll/NL/`) measurably helped marker recall at
   60fps (71-73% vs ~44-56% lit). The 240fps NL clips measured worse, but that was later
   attributed to a since-fixed detection bug + small sample, not exposure — **re-measure NL at
   240fps if pursuing this**, not yet done.
3. 240fps's blur-reduction benefit (shorter shutter, less motion blur during approach/
   separation) is real and separate from rotation sampling (which is oversampled even at
   60fps). The tradeoff is exposure — the available bright light flickers above 60fps.
   **Superseded by #6 below** — moot now that the deliverable is locked to a 60fps webcam.
4. **Repositioning to the other side of the table**: tried 2026-09-17 (`Other_Side.mp4`).
   Tradeoff observed by eye: noticeably more shadow from that side. A same-session, per-clip
   color-blob disk count (classical CV, not YOLO — see Model section for why) found more
   disk-body detections in `Other_Side` (70 green / 151 blue) than either
   `Previous_Side_Light` (25 / 49) or `Previous_Side_No_Light` (0 / 51) — but this is **not a
   controlled comparison** (each clip is a different throw/trajectory, so more time
   on-camera confounds the count) and shouldn't be read as "shadow beats glare" without a
   same-trajectory repeat. Notable on its own regardless of cause: `Previous_Side_No_Light`
   had zero green-disk color detections in 374 frames — worth a specific look at whether that
   clip's green disk was in frame/orientation to be seen at all before concluding anything
   about the no-light condition itself.
5. **4K resolution**: would help marker precision in principle, but **moot — superseded by
   #6**, the deployment camera is a 1080p webcam with no 4K mode.
6. **Hardware decision (2026-09-17): webcam-only, no external hardware.** Professor requires
   the project not depend on external hardware (no dedicated camera/phone purchase for the
   pipeline itself). Deployment target is fixed at **1080p @ 60fps via webcam** — this is not
   a stopgap, it's the actual spec to validate and tune against going forward. This resolves
   #3 and #5 above (fps/resolution tradeoffs against phone slow-mo no longer apply) and
   reinforces #2 (60fps is already the known-good operating point from prior NL testing).
   A phone may still be used later for one-off calibration/reference footage, but the shipped
   pipeline must work on webcam 1080p60fps footage.

## Known bugs / open issues

1. **Still open**: a known false-positive marker match (`240_25.mp4` disk 0, frame 368,
   returns a wrong color, not a missed detection) is not caught by the sigma-clip fit even
   though that segment's fit is otherwise trustworthy (residual std ~1.94°) — the bad value's
   residual apparently isn't large enough relative to that tight fit to get flagged. Not
   automatically fixed by the recovery/interpolation pass either (that only overwrites rows
   already flagged missing/inconsistent). No dedicated fix attempted — real fix is expected to
   be the repaint (removes this failure mode's root cause: the two-dimple / low-saturation
   material problem), not further per-case tuning.
2. `estimate_background_median` only masks pixels a puck was *detected* covering during the
   sample window — if a puck sits somewhere YOLO doesn't detect it at all during that window,
   that spot still isn't protected. Edge case, not hit in testing so far.

## Reference: local test footage

- `Camera Roll\NL\` — no-glare lighting test clips (NL01/02 = 60fps; NL03-05 = 240fps,
  inconclusive, see Lab history #2).
- `Camera Roll\Novos Videos\` — 28 videos (`240_1`...`240_25`, `new01`-`new03`), training-set +
  calibration-survey source. Not representative of real single-collision runs.
  `extracted_frames\has_pucks\` (884 frames, not in repo) is a pre-filtered puck-visible subset
  for quick surveys.
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
