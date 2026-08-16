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

## Standing objective (until new footage exists)

**User is repainting the disks** (whole disk colored, marker becomes a black dimple — see
"Marker detection: two schemes" below) but can't do that or shoot new footage until back in
the lab, target **2026-08-30**. Until then: **lay as much groundwork as possible against
current footage so that once new footage exists, remaining work is minimal — ideally just
retuning HSV constants against real paint samples, not writing or restructuring logic.**
Judge new work by this bar: does it stay directly useful post-repaint with no rework? Current
footage (`Novos Videos`/`NL`) is dataset-building/test footage, not real collision runs — no
new real data to work from until the lab trip.

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

Single active branch: **`deepLearning`**.

### Detection pipeline (`detector.py`)

- **Disk position**: YOLO Pose (single class `puck`, 2 keypoints `[center, marker]`),
  `detect_disks_yolo()`, `conf=0.10`, `imgsz=1280`. Solid/near-perfect once a puck is in frame
  — see Model section. **Treat bbox radius as noisy, not ground truth** (measured cases
  underestimating the true disk by >3x) — never build tight geometry off a single frame's
  bbox; `scale_mm_per_px` uses the median of the first 8 YOLO-sourced radii
  (`RADIUS_SAMPLE_TARGET`) for exactly this reason.
- **Fallback**: `fallback_contour_disks()` (background-subtraction contour), only when YOLO
  found <2 disks, only within `FALLBACK_SEARCH_RADIUS_PX` of a missing disk's *predicted*
  position (see `IDAssigner.predicted_pos`, not a stale last-seen one), radius-gated so
  glare/reflection blobs can't slip through.
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

`detector.MARKER_SCHEME` selects which runs — **`"classic"` is the default and what any
current run actually uses.**

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
- **`"flipped"`** (future, repainted disks — whole disk colored, marker = black dimple):
  `resolve_marker_flipped_scheme()` / `Pre_process.classify_disk_bulk_color()` (disk identity
  via majority-vote color match over the whole disk interior, ≥15% share required) +
  `Pre_process.detect_dark_marker_center()` (marker = darkest compact blob within the disk,
  threshold relative to that disk's own median V). Shares crop/geometry/contour-selection
  logic with the classic path via `Pre_process._select_best_blob`. Placeholder constants
  (`FLIPPED_GREEN_LOWER/UPPER`, `FLIPPED_BLUE_LOWER/UPPER`, `FLIPPED_MARKER_DARK_VALUE_FRAC`,
  `FLIPPED_MARKER_MIN_AREA_FRAC`, `FLIPPED_MARKER_MIN/MAX_CIRCULARITY`, all in `detector.py`,
  clearly marked) currently just inherit the classic scheme's calibrated values — **expect
  these to need real retuning, not just reuse**, once real painted samples exist. Validated
  only synthetically (idealized solid-fill circles) — no real footage of this scheme exists
  yet, so treat it as structurally sound but unvalidated against real noise/glare/paint
  texture. **Paint spec** (if repainting): matte/flat finish only (no gloss/metallic — glare
  was the #1 recurring root cause of false marker matches), spray paint formulated for
  plastic (not craft acrylic — these disks take repeated impacts), stay in the green/blue
  family but saturated mid-tones (kelly/emerald green, royal/cobalt blue — avoid pastels,
  red/orange, navy, neon), marker dimple painted black (not left bare) and the disk's *other*
  (non-marker) dimple filled/painted to match the body so it stops being a second candidate
  feature. Test one disk under real lab lighting before committing the full set.

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
  more images of the same kind won't move it).
- **Position/box detection is solid and validated.** **The marker keypoint is unreliable**
  (~44% land on a non-marker specular highlight) and is **not used** by the pipeline — marker
  localization is 100% classical CV, independent of this keypoint.
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
   60fps). The tradeoff is exposure — the available bright light flickers above 60fps. Don't
   trade away fps to fix lighting; fix the light source (flicker-free/high-PWM, or more
   diffuse LEDs) instead.
4. **Worth testing first, not yet validated**: repositioning the table/collision so the glare
   reflection falls outside frame, instead of relighting — keeps full brightness, sidesteps
   the exposure tradeoff entirely if the geometry works out.
5. **4K resolution**: recommended if the camera supports a still-decent fps at 4K (120fps+) —
   more pixels directly helps the marker's precision problems. Check actual supported
   resolution/fps combos first (4K@240fps is uncommon); don't trade away fps for resolution
   without first checking how many frames of actual contact a collision shows at each
   candidate fps (short contact + low fps risks losing the collision event itself).

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
