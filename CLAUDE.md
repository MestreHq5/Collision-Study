# Collision-Study (DEM) — Project Context

> This file is read automatically by Claude Code at the start of sessions in this repo.
> Keep it updated as the project evolves — add new bugs, remove resolved ones, log decisions.

## What this is

Python/PyQt6 desktop app that analyzes 2D collisions of two circular pucks on an air table
from video footage, tracking position/orientation/kinematics per frame and exporting
scaled physical metrics (mm, s) to CSV for Discrete Element Method (DEM) validation.

- Disk 0 = Green marker, Disk 1 = Blue marker
- Disk diameter: 70.0 mm (35mm radius, user-confirmed; was wrongly coded as 80.0mm for a
  while — this drove `scale_mm_per_px`, so it silently scaled every mm value ~14% high until
  fixed), default mass: 0.0118 kg
- Offset marker sits ~20-30mm from disk center (user-measured), circular, colored blue or green
- Disk **bodies** are gray/slate — only the small offset marker dot is colored. Any detection
  logic that assumes the whole disk is colored will fail.
- **Physics**: air table is frictionless (user-confirmed) — angular velocity is expected
  constant between collisions, no torque except during contact. Validated on real footage:
  unwrapped marker angle decreases ~1°/frame consistently over 100+ frame stretches pre/post
  collision.
- **Filming pattern**: real collision videos are a single collision each — two disks
  approach, contact once, separate ("draws an X"). Not multi-bounce. Simplifies rotation
  segmentation to exactly two segments (before/after) per video, always.
- The `Camera Roll/Novos Videos/` clips used for most of this project's testing/training were
  recorded to build the deep-learning dataset, not as real collision-study runs — expect
  varied/non-representative trajectories there, unlike the real single-collision footage above.

## Architecture

```
Collision-Study/
├── initializer.py    # Entry point; sets Windows DPI awareness BEFORE Qt import
├── app.py             # PyQt6 GUI (file selectors, FPS inputs, process triggers)
├── helper.py          # Bridges GUI calls to backend pipeline
├── detector.py        # Core pipeline: video I/O, detection, ID tracking, CSV export
├── Pre_process.py     # CV utilities (HSV filtering, marker isolation, background estimation)
├── Post_process.py    # CSV -> kinematics/rotation/Excel + collision metrics
├── train.py           # Retrains the YOLO Pose model from Puck_Training/ (see Model section)
└── runs/pose/train-5/weights/best.pt   # Fine-tuned YOLO Pose model (deployed — see below)
```

Single active branch: **`deepLearning`**. Detection pipeline in `detector.py`:

- **Primary: YOLO Pose** (single class `puck`, 2 keypoints `[center, marker]`) —
  `detect_disks_yolo()`. Disk center prefers the "center" keypoint (falls back to bbox center
  if low-confidence); radius comes from the bbox — **treat the bbox radius as noisy, not
  ground truth**: measured cases on real footage where it underestimated the true visible disk
  by >3x. Don't build tight geometry (search radii, masks) on a single frame's bbox radius;
  prefer a run-level robust estimate (median over several frames) if precision matters.
  `conf=0.10`, `imgsz=1280`. `remove_duplicate_detections()` dedupes boxes within 30px.
- **Marker color**: `resolve_marker_color()` scans a generously padded crop around the disk
  (`MARKER_SEARCH_PAD_FACTOR = 3.5`), excluding only a small central disc
  (`MARKER_DIST_MIN_FRAC = 0.3`). No keypoint-anchored fallback, no outer distance bound —
  both were tried and both clip real markers whenever that frame's bbox underestimates the
  disk (see above). Precision against background comes from HSV color range +
  `MARKER_MIN_AREA_FRAC`/`MARKER_MIN_CIRCULARITY`/`MARKER_MAX_CIRCULARITY` + `IDAssigner`'s
  position-lock. Calibrated from a broad survey (580 marker samples across all 28
  `Novos Videos` clips, not 1-2 clips). `detect_marker_center`'s CLAHE tile grid and
  morphological kernel both scale to the actual crop/disk size (fixed pixel constants silently
  broke on footage with a different object scale than whatever was last tuned).
  **`detect_marker_center` picks the largest contour that *passes* the shape gates, not the
  largest contour full stop** — picking largest-then-checking-shape was a real bug (a genuine
  marker got fused with adjacent background by the mask-cleanup step into one large, irregular
  blob that failed circularity, while a separate small, valid, correctly-round marker blob sat
  right next to it in the same mask and was never even considered). Fixing this took whole-
  dataset marker recall from 42.8% to **60.5%** (`has_pucks` survey, 1004 disk detections) —
  the "40-45% ceiling" language from earlier in this project's history is now stale; that
  ceiling was this bug, not a fundamental HSV/shape-heuristic limit. Considering *every*
  contour did surface a new, narrower failure mode — a small (~28px) noise/compression
  artifact can be *more* circular than real paint (0.943 vs 0.72-0.83 confirmed real) — hence
  `MARKER_MAX_CIRCULARITY = 0.90` as a companion ceiling.
- **Fallback: background-subtraction contour** (`fallback_contour_disks()`) — only when YOLO
  found <2 disks, only within `FALLBACK_SEARCH_RADIUS_PX` (250px) of a missing disk's last
  known position, gated by radius (0.5x-1.8x of a reference radius) so glare/reflection blobs
  can't slip through just because they're circular.
- **ID logic**: `IDAssigner` — position-lock runs before color (a detection within
  `POSITION_LOCK_GATE_PX` (60px) of an already-tracked ID's last position claims that ID
  immediately); color only decides identity for genuinely new/gapped tracks. This is what
  makes the pipeline robust to color being wrong or absent — a bad single-frame color read
  can't corrupt an established track's identity anymore. Plain class, not a
  `PersistentDiskTracker` (that name never existed in this codebase, despite older notes).
- `scale_mm_per_px` is computed from the **median of the first 8 YOLO-sourced radii**
  (`RADIUS_SAMPLE_TARGET`), not a single first detection — guards against exactly the bbox
  anomaly above corrupting every mm value for an entire run.

## Model (YOLO Pose)

- **Deployed**: `runs/pose/train-5/weights/best.pt`. 487 labeled images / 588 labeled puck
  instances (`Puck_Training/`), imgsz=1280, single class `puck`, `kpt_shape=[2,3]`
  (`[center, marker]`). Training curve plateaus around epoch 8-14 (pose mAP50 oscillates
  0.70-0.81 for the remaining ~20 epochs, no sustained improvement) — **this is a converged
  model, not a data-starved one**; more images of the same kind are unlikely to move it much.
- **Position/box detection is solid and validated** across many real clips (near-perfect once
  a puck is actually in frame). **The marker keypoint specifically is unreliable** (measured:
  lands on a non-marker specular highlight ~44% of the time) and is not used by the pipeline —
  marker localization is 100% classical CV (`resolve_marker_color`), independent of this
  keypoint.
- **Lesson on trusting isolated metrics**: `ultralytics`' pose mAP is aggregated over both
  keypoints, and has now been shown twice to *not* predict real pipeline performance — trust
  the end-to-end pipeline test (`detect_disks_yolo` + `resolve_marker_color` against the
  `has_pucks` survey), not the training-run mAP, when evaluating a checkpoint.
  1. **`runs/pose/Puck_Runs/240fps_trial_02-2`** scored higher in isolated pose-mAP (0.883 vs
     train-5's 0.812, same dataset) but **did not translate to a better end-to-end result**:
     41.6% marker coverage vs train-5's 44.2% — a wash, slight edge to train-5. Not switched.
     (That run also degraded to ~0.50 mAP by epoch 100 with no early stopping configured — only
     its `best.pt` is usable, not `last.pt`.)
  2. **`runs/pose/marker_weighted`**: hypothesis was that `ultralytics`' pose loss weights all
     keypoints equally by default (`sigmas = ones(nkpt)/nkpt` = `[0.5, 0.5]` for our 2-keypoint
     case), so training was never pushed to prioritize the harder marker keypoint over the
     trivially-easy center one. Retrained from scratch with `sigmas=[0.7, 0.3]` (center,
     marker) via a callback patch (`model.criterion.keypoint_loss.sigmas`, not exposed through
     `args.yaml`/`train.py` directly). Result: marker coverage barely moved (46.6% vs 44.2%,
     within noise for this sample size) and, measuring keypoint-to-true-marker distance
     directly (not just aggregate mAP), the keypoint's own accuracy got *worse*, not better
     (40.3% of colored detections had the keypoint within 0.5 disk-radius of the HSV-confirmed
     true marker, vs 53.8% for train-5). **Not switched.** One run isn't proof the theory is
     wrong (real variance exists between individual training runs — see the mAP oscillation
     noted above), but it didn't validate the theory either; would need multiple seeds/sigma
     values to know for sure, which wasn't judged worth the GPU time given the physics-recovery
     plan below doesn't depend on this working.

## deepLearning vs. classical OpenCV contour

Settled, not an open question — **keep YOLO for disk position/tracking**. Classical contour
detection was tested against the new lab's lighting and failed specifically because of glare,
independent of blur/shutter (see Lab/lighting history below); YOLO position tracking has since
been validated near-perfect on the same conditions. There's no evidence classical would do
better there, and real evidence it does worse.

Note this was never really a YOLO-vs-classical question for the *marker* problem specifically:
marker color/position has been 100% classical CV for a while now (YOLO's marker keypoint is
unused — see Model section). The marker struggle is the classical method hitting the same
glare problem that broke classical position-tracking in the old lab comparison, just now on
the marker instead of the whole disk.

## Lab / lighting history

1. Old lab, webcam, 60fps, natural light — classical contour detection worked well, even with
   real motion blur present.
2. New lab, same webcam, artificial overhead lighting — glare broke classical detection.
3. New lab, phone camera (sharper, ~no motion blur) — classical **still** underperformed. Key
   signal: the new lab's glare is the actual problem, not camera shutter/blur — this is what
   motivated the switch to YOLO for position tracking.
4. **New lab rig**: 6 intense LED bars total, with some subset (2-3) directly above the table
   causing the glare above. Camera choice was never actually the deciding factor in #2/#3 above
   (webcam *and* phone camera both failed under the same lighting, both worked once lighting
   was fixed) — don't expect switching cameras alone to fix a lighting problem.
5. **NL (`Camera Roll/NL/`) = the bars directly over the table switched off.** Checked whether
   this fixes the marker problem specifically (same root cause as #2/#3, now hitting classical
   marker detection instead of position): **at matched ~60fps, marker coverage is 71-73%**
   (NL01/02) **vs ~44-56% for lit footage at similar fps** — a real, substantial improvement,
   confirms glare is genuinely the dominant driver of marker-detection failures. The 240fps NL
   clips (NL03-05) measured only 22-26% at the time, which first looked like an underexposure
   problem (dimmer than the 60fps NL clips) — **that explanation didn't hold up**: brightness
   turned out comparable to lit-240fps footage when checked properly, and a visible NL marker
   sampled directly landed squarely inside the calibrated HSV range. The real cause was more
   likely the largest-vs-best-contour bug (see Architecture) plus a small sample (only 30-70
   disk detections tested per NL clip) — not exposure. **NL-240fps hasn't been re-measured
   since fixing that bug; do that first before drawing any conclusion about high-fps NL
   footage.**
6. **fps and motion blur**: higher fps forces a shorter shutter, which genuinely reduces linear
   motion blur during the fast parts of the trajectory (approach/separation velocity) — this
   was a correct reason to prefer 240fps, not a mistake. Separately, *rotation* specifically is
   slow enough (~1°/frame at 240fps, i.e. ~240°/s) that 240fps oversamples it enormously (60fps
   would still give ~90 samples/revolution) — so 240fps isn't *needed* for rotation tracking,
   but that's not an argument against it either, since the blur-reduction benefit is real and
   separate. The actual tradeoff is exposure: shorter shutter needs more light, and the
   available bright supplemental light flickers above 60fps (unusable at 240fps). Don't trade
   away fps to fix this — solve the light source instead (a flicker-free/high-frequency-PWM
   light, or more of the existing diffuse LED bars) if staying at 240fps once back in the lab.
7. **Geometric alternative worth testing first**: repositioning the table (or shooting the
   collision at the opposite end of the table) so the glare reflection falls outside the
   recorded frame, instead of turning off table-overhead lights at all. This avoids the
   exposure tradeoff in #6 entirely — full brightness kept, glare just isn't in frame. Not
   validated yet (no footage to check), but structurally the better option if the geometry
   works out, since it sidesteps the light-vs-exposure problem rather than trading one for the
   other.
8. **Resolution (4K)**: recommended as a real, low-tradeoff upgrade *if the camera supports a
   still-decent fps at 4K* (120fps+) — more pixels on the small marker directly helps the
   precision problems hit repeatedly this project (imprecise sub-pixel localization, boundary
   jaggedness affecting shape checks). Check the camera's actual supported resolution/fps
   combinations before committing — 4K at 240fps is uncommon on consumer hardware, so this may
   come down to trading some fps for resolution rather than getting both; given point 6, don't
   make that trade if it costs the blur-reduction benefit without checking first how many
   frames of actual contact a real collision shows at each candidate fps (short contact +
   dropped fps risks losing the collision event's own dynamics almost entirely, which matters
   more for this study than steady-state rotation sampling).

## Known bugs / open issues

1. **Still open, genuinely unsafe: known false-positive marker match (`240_25.mp4` frame 368)
   still returns a wrong answer ("green"), not just a missed detection.** Checked whether
   tonight's two fixes (largest-vs-best-contour selection, `MARKER_MAX_CIRCULARITY`) touched
   it — they don't: this case's circularity (~0.79) sits inside the confirmed-real range
   (0.72-0.83) on both sides, so no circularity bound alone can separate it from a genuine
   marker. `IDAssigner`'s position-lock still protects an established track's *identity* from
   this (documented, unrelated to tonight), but the `marker_color`/position *values* written
   for that frame are simply wrong — not a safe null result. Not chased further tonight (would
   need per-case threshold hacking with no principled stopping point); the physics-assisted
   recovery plan below is the intended real fix (motion-consistency check catches this
   structurally — a physically implausible marker jump gets rejected regardless of how
   "valid-shaped" the blob looks), and is next up.
   - Encouraging data point from tonight: a *different* near-identical failure mode (small,
     suspiciously-perfect blob) that the max-circularity fix newly exposed *did* resolve safely
     — to `None`, not a wrong answer (see `new01.mp4` frame 220 in this session's testing). So
     the fix's direction is right; frame 368 specifically just isn't caught by it.
2. `IDAssigner`'s nearest-neighbor step (for detections beyond the position-lock gate) has no
   maximum distance check — relevant for a disk reappearing after a multi-frame gap. A
   velocity-gated lock (extrapolate from last 2-3 positions) would fix this and let the contour
   fallback search from a predicted position instead of a stale one.
3. `estimate_background_median()` assumes the first `CLEAN_SECONDS` of video has no pucks on
   the table — if one's already in frame at t=0, `scale_mm_per_px` and the contour fallback
   degrade for the whole run.

## Rotation / marker detection — live plan

**Where this stands**: disk position/ID tracking is solved. Marker color/rotation coverage was
the remaining weak point — **60.5%** as of tonight (`has_pucks` survey, 1004 disk detections),
up from 42.8% after fixing the largest-vs-best-contour bug (see Architecture, Marker color).
Not by markers being physically invisible (checked earlier: 0% of failing detections in that
survey have no visible colored blob at all — every miss is the algorithm rejecting something
real) — so there's likely still room above 60.5% from the same category of fix, though nothing
else this concrete was found tonight.

**Goal**: fill the whole rotation column (every frame gets a usable angle), via recall
improvements *and* physics-based recovery/interpolation, not recall alone.

**This is the plan for the next session** (nothing below has been implemented yet — tonight
was diagnosis + the two contour-selection fixes above):

0. **First thing next session**: RANSAC/sigma-clipping step 2 below will itself flag frames
   like `240_25.mp4` frame 368 as trend-inconsistent outliers once it's built, which is a more
   principled fix than another shape-heuristic patch — so bug 1 above doesn't need its own
   dedicated fix, just build step 2 and confirm it catches this case as a sanity check.
1. Segment each disk's timeline at the collision frame (`_find_collision_frame` already exists
   in `Post_process.py`) — always exactly 2 segments per real video (see "Filming pattern"
   above). Never fit/interpolate across a segment boundary — ω is not expected constant there
   (contact torque), and that region is measurably noisier already (checked on `240_25.mp4`
   near its collision frame).
2. Robustly fit angular velocity per segment (RANSAC / iterative sigma-clipping linear
   regression of unwrapped θ vs. frame) using only currently-passing detections — both gives a
   per-segment ω estimate and flags which existing detections are trend-consistent vs. false.
3. Physics-assisted recovery: for frames with no/rejected detection, predict marker position
   from the segment fit, then run a narrow, high-sensitivity confirmation search there (safe
   now because location is already constrained by physics, not a blind per-frame search). This
   is the mechanism expected to move recall from ~60% toward 80%.
4. Fill whatever's still missing by interpolation/extrapolation from the fit, writing an
   explicit `theta_source` column (`measured`/`recovered`/`interpolated`) so downstream DEM
   analysis can weight or exclude non-measured values.
5. Re-measure recall and interpolation error against a held-out set of currently well-covered
   segments before trusting it on sparse ones.
6. If 1-5 doesn't reach the target, or the collision window specifically still needs better
   real detection (interpolation structurally can't cover it): the one sigma-reweighted
   retrain attempted so far didn't pan out (see Model section) — a dedicated learned marker
   classifier bootstrapped from `has_pucks` + this pipeline's own QA'd detections is the more
   promising remaining ML option, or a properly resourced retrain (more seeds, real
   hyperparameter search, ideally new labels from better-lit/repainted footage) rather than
   the single quick experiment tried here.
7. Parallel, non-blocking, whenever back in the lab: matte (not glossy) marker paint, and pair
   any glare reduction with *more diffuse* light if shooting at high fps (see NL finding
   above). Confirmed safe to do — repainting doesn't invalidate the deployed model's position
   detection (independent of marker color) or the existing labeled dataset (its disk-detection
   portion stays exactly as useful); it mainly means recalibrating the classical HSV layer
   (cheap, same broad-survey method already built) and, if pursuing item 6, collecting new
   labels for a future keypoint retrain.

## Directives (carried over from original briefing)

1. ~~YOLO detection filtering: keep `conf` ~0.10-0.15, dedupe candidate boxes.~~ **Done.**
2. ~~Motion/background fallback only in expected disk regions when YOLO detects <2 disks.~~
   **Done** (`fallback_contour_disks`).
3. Trajectory-based persistent ID lock: **partially done** — position-lock-before-color is a
   fixed-distance gate, not the originally-specified velocity-extrapolated one (see bug 2
   above). Superseded in priority by the rotation-recovery plan, which needs its own
   RANSAC/velocity fitting anyway — worth doing both together if picked up.

## Reference: local test footage

- `Camera Roll\NL\` — no-glare lighting test clips (NL01/02 = 60fps, clearly better than lit;
  NL03-05 = 240fps, inconclusive — re-measure after the contour-selection fix, see Lab/lighting
  history above).
- `Camera Roll\Novos Videos\` — 28 videos (`240_1`...`240_25`, `new01`-`new03`) used to build
  the training dataset and for broad calibration surveys this project relies on. Not
  necessarily representative of real single-collision runs (see "What this is" above).
  `extracted_frames\has_pucks\` (884 frames, not checked into the repo) is a pre-filtered
  subset with a puck visible — use this instead of scanning full videos for quick surveys.
- `Videos/` in the repo itself was cleared out — don't expect test footage there.


## Long Term Issues (Not critical)

- Correct the DPI warning (correct or supress, not sure). 

- Add a loading screen or something that shows the progress once hiting the generate button and before the preview is available.


## Working preferences

- User is Aerospace Engineering student, comfortable with Python/CV concepts, values direct
  technical explanations over hand-holding.
- Prefers to receive full code/analysis upfront and make editorial decisions independently.
- Expressed strong trust/urgency around the rotation-column goal ("white pass to change
  anything, I just need this to work") — reasonable to move fast on changes clearly in service
  of that plan without re-confirming each one, but this isn't blanket authorization for
  unrelated or destructive actions; normal judgment on risk/reversibility still applies.
- User is heading back to the lab on the end of the month — plans to record new footage there (likely 4K, resolution/fps TBD per
  the Lab/lighting history discussion above) and wants help picking up again once that footage
  exists. Until then, this project has no new real data to work from — the `Novos Videos`/`NL`
  footage is what's available, and it's dataset-building/test footage, not real collision runs
  (see "What this is").
