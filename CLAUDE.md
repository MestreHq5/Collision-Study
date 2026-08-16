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
├── initializer.py    # Entry point; just imports app and calls app.main()
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

0. **New session, real-footage diagnostic that reshaped the marker-search design**: user tested
   `240_15.mp4` — a disk sitting completely motionless for long stretches (frames 509-739 and
   829-999, confirmed by cx/cy std < 1px and cross-checked against the raw frames). Since the
   disk isn't moving, the true marker position is fixed in absolute pixels, so any detected
   movement is pure detection noise — a clean ground-truth test unavailable on any moving
   footage. Result before tonight's fix: center detection was rock solid, but the marker landed
   6.6-43.8px from the disk center against a measured disk radius of only ~11-16px — i.e.
   regularly **outside the physical disk entirely**, and `marker_color` flipped between
   green/blue almost every other frame for the same motionless disk. Pulled full-resolution
   frames to see why: the disk material is near-black (HSV hue/saturation are inherently
   unstable at low value), the documented second unpainted dimple sits right next to the real
   (small, only moderately saturated) blue paint dot, and an overhead glare streak crosses the
   disk's screen position in multiple frames — three compounding causes, not one. One especially
   clean piece of evidence: 6 consecutive frames locked onto the *exact same pixel*, 41px from
   the true center — a static false-positive on a background/table feature, not marker jitter.
   **Fix applied**: `resolve_marker_color`/`MARKER_SEARCH_PAD_FACTOR` (`detector.py`) now hard-
   bounds the marker search to the disk's own physical 35mm radius (`DISK_RADIUS_MM`) once
   `scale_mm_per_px` is calibrated, keyed off the run-level scale estimate rather than any
   single frame's noisy YOLO bbox radius (which is what broke an earlier attempt at this same
   bound — see the docstring in `detector.py` for the full reasoning). Re-ran the same
   stationary-disk test after the fix: **max detected distance dropped from 43.8px to 10.9px,
   mean from ~28-33px to ~6.7-7.5px** — confirms detections are now confidently on the physical
   disk, never off in the background. This is a real, verified win for precision, but it is not
   a full fix and was not expected to be one: angle std is still ~100-122° (the color-flip/two-
   dimple/low-saturation problem is untouched — geometry alone can't tell the real marker apart
   from the unpainted dimple sitting a few px away on the same disk), and recall dropped
   further in the noisier/more glare-affected window (35% -> 6%) — consistent with, and now a
   second independent confirmation of, the recall cost already documented once before for this
   exact kind of bound. Accepted deliberately: user's priority here is precision/containment
   over recall on this pre-repaint footage ("leave detection as flawless as it can be without
   the new disks"), and a wrong-but-plausible value is worse for downstream physics than a
   missing one. Real fix for the color-flip/angle-noise problem itself is still the planned
   repaint + relighting (see live plan below), not further classical-CV tuning on this material.

1. **Still open, genuinely unsafe: known false-positive marker match (`240_25.mp4` frame 368)
   still returns a wrong answer ("green"), not just a missed detection.** Checked whether
   tonight's two fixes (largest-vs-best-contour selection, `MARKER_MAX_CIRCULARITY`) touched
   it — they don't: this case's circularity (~0.79) sits inside the confirmed-real range
   (0.72-0.83) on both sides, so no circularity bound alone can separate it from a genuine
   marker. `IDAssigner`'s position-lock still protects an established track's *identity* from
   this (documented, unrelated to tonight), but the `marker_color`/position *values* written
   for that frame are simply wrong — not a safe null result.
   - Encouraging data point from an earlier session: a *different* near-identical failure mode
     (small, suspiciously-perfect blob) that the max-circularity fix exposed *did* resolve
     safely — to `None`, not a wrong answer (see `new01.mp4` frame 220). So that fix's
     direction is right; frame 368 specifically just isn't caught by it.
   - **Update (this session): built and real-footage-tested the segmentation + robust omega fit
     (Rotation plan step 2 below, `Post_process.fit_rotation_segments`) that step 0 of that plan
     predicted would catch this case structurally — it did not, for a more specific and more
     concrete reason than "not caught yet".** Reran the actual detection pipeline
     (`detect_disks_yolo`/`resolve_marker_color`/`IDAssigner`, unmodified) on the real clip,
     frames 0-899, in px space (bypasses the CSV export's scale-not-ready gate that was
     silently dropping every pre-frame-372 detection, including 368, from prior CSV-based
     looks at this bug). Confirmed frame 368 is disk 0, `marker_color="green"`, matching the
     original report. But the surrounding window (disk 0, frames 365-591 — the only stretch of
     this clip where disk 0 is on-screen in the first 900 frames; disk 1 doesn't appear until
     frame 672, zero frame overlap between them in this range) is **far noisier than assumed**:
     measured disk radius there is only ~11-16px (tiny — consistent with the long-documented
     "bbox radius is noisy, sometimes badly underestimates the true disk" warning above, and at
     that radius a 1-2px marker-centroid error alone is ~9-10 deg of angular error), and several
     nearby frames (397, 399, 401) have `marker_color` alternating "green"/"blue" *on the same
     physically continuous disk* (position track is smooth through all of them, ruling out an
     `IDAssigner` mix-up) — a color misclassification, not just an angle error, and a new
     concrete instance of the "false marker" problem distinct from the frame-368 case itself.
     Altogether ~36% (51/141) of this window's marker detections are inconsistent with any
     single linear trend — the fit correctly flagged the 397/399/401 color-misread frames as
     outliers, but at this corruption level frame 368's specific value doesn't stand out enough
     from its immediate (also-somewhat-noisy) neighbors to be individually flagged. This is a
     real limitation, not a bug: 400 synthetic trials (varying recall 30-95%, 0-3 injected
     bad-but-plausible points per ~100-250-point segment, i.e. up to ~a few percent corruption)
     all recovered the true omega to within 0.15 deg/frame, and a *clean* real window from the
     same clip (disk 1, frames 672-857, same tiny ~12px radius) fit with **zero** flagged
     outliers and omega=0.76 deg/frame, in line with the ~1 deg/frame expectation — so the
     mechanism itself works; this specific window is just far more corrupted (~36%) than
     anything tested against so far, well past what a single global per-segment linear
     sigma-clip fit can be expected to individually resolve. Frame 368 is downgraded from "the
     next thing to fix" to "a symptom of this window's corruption level, likely needing the
     physics-assisted recovery search (step 3) and/or a marker-localization precision fix (see
     roadmap item 4 / resolution item 8) rather than a smarter fit on top of the same noisy
     per-frame marker reads" — not chased further as an isolated case tonight.
2. ~~`IDAssigner`'s nearest-neighbor step... has no maximum distance check.~~ **Done** —
   `IDAssigner` (`detector.py`) now tracks a 2-position history per ID and a per-ID gap counter
   (frames missing since last confirmed sighting). Step 3 (beyond the position-lock gate) now
   matches against a *predicted* position (last position extrapolated by last-known velocity ×
   gap) gated at `MAX_SPEED_PX_PER_FRAME * gap`, rejecting an implausibly-far "best available"
   candidate instead of force-assigning it — previously the sole remaining candidate always won
   regardless of distance, and that wrong position then became the new "last known position"
   for every future frame's lock/prediction with no way to recover. Exposed
   `predicted_pos(pid)` publicly and wired the contour fallback (`main()`) to search from it
   instead of the stale last-seen position, per the original plan. Caught two of my own bugs
   before shipping, both worth noting: (a) an off-by-one in the gap counter (fixed by having
   both step 3 and the public `predicted_pos()` read the same `_current_gap()` — `gap + 1` —
   instead of the stored value directly, so a call from `main()` between frames and a call from
   inside `assign()` agree); (b) step 4's "deterministic fallback, no history" branch was still
   force-assigning IDs step 3 had just correctly rejected, silently undoing the whole gate —
   fixed by restricting step 4 to genuinely history-less IDs only. Verified with a synthetic
   unit test (steady velocity + gap reacquisition within the gated window + an absurdly-far
   candidate correctly left unassigned) and an end-to-end smoke test on real footage
   (`240_15.mp4`, 700 frames through `detector.main()` unmodified) — no crashes, sensible
   output.
3. ~~`estimate_background_median()` assumes the first `CLEAN_SECONDS` of video has no pucks on
   the table.~~ **Done** — added an optional `puck_masker` callback
   (`Pre_process.estimate_background_median`); `detector.main()` now loads the YOLO model
   *before* background estimation (order flipped for this reason) and passes a closure that
   YOLO-detects pucks in each sampled background frame, excluding those pixels from that
   frame's contribution to the median instead of trusting the whole window blindly. Where a
   pixel is covered in every sampled frame (no clean data exists anywhere), falls back to the
   plain median there — an honest limit, not fixable without more/different data. First
   implementation tried a dense per-frame NaN-mask + `np.nanmedian` over the whole stack and hit
   an out-of-memory error on a real 1080p run (`numpy`'s `nanmedian` falls back to a
   masked-array sort internally, which is not memory-lean) — switched to only recomputing the
   (typically small, puck-footprint-sized) actually-occluded pixels individually, which is both
   correct and cheap since a puck touches a tiny fraction of the frame. Verified with synthetic
   video against three cases: a pixel never covered (unaffected, as expected); a pixel covered
   in *every* sampled frame (correctly falls back to the honest-limitation plain median, still
   contaminated — nothing else is possible); and the real target case, a pixel covered in a
   *majority but not all* sampled frames (10/15 = 67%, enough to break the old plain median) —
   correctly recovered the true background color from the clean minority. Also fixed end-to-end
   via the same `240_15.mp4` smoke test as bug 2 above (no crash, same detection output as
   before on a clip whose own clean window happens to be puck-free, as expected — this fix is a
   no-op safety net on that particular clip, not a behavior change on it).

## Rotation / marker detection — live plan

**Where this stands**: disk position/ID tracking is solved. Marker color/rotation coverage was
the remaining weak point — **60.5%** as of tonight (`has_pucks` survey, 1004 disk detections),
up from 42.8% after fixing the largest-vs-best-contour bug (see Architecture, Marker color).
Not by markers being physically invisible (checked earlier: 0% of failing detections in that
survey have no visible colored blob at all — every miss is the algorithm rejecting something
real) — so there's likely still room above 60.5% from the same category of fix, though nothing
else this concrete was found tonight.

**Root-cause note (user, confirmed real via `240_22.mp4`)**: each disk has *two* dimples for
physical symmetry/balance, only one of which is painted as the marker. The unpainted dimple is
sometimes picked up as a false marker (visible as ~10 spurious same-disk detections early in
`240_22.mp4`, before the green disk exits frame) — likely because a bare recessed dimple can
catch a shadow/reflection that reads as color-ish, giving it a plausible-enough HSV signature.
This is a second, distinct source of false positives from the "small noise blob" one found
this session (see `MARKER_MAX_CIRCULARITY` above) — same failure *category* (something that
isn't the marker gets mistaken for it), different physical cause (a real, consistent physical
feature, not per-frame image noise).

**Design idea raised (user) — paint the whole disk instead of just the marker, marker becomes
the disk's bare gray/black material**: recommended, for a concrete reason beyond "bigger
target" — searching for the *darkest/least-saturated spot inside a known colored region* is
structurally more robust than searching for a *specific saturated hue against a similarly-toned
background*, because glare/specular highlights are bright — under the current scheme they can
be confused with the (bright, saturated) marker; under the flipped scheme they'd work *against*
a false match instead of mimicking one. This would also make disk *identity* (which disk is
green vs blue) far more robust than it can ever be from a small offset dot, sidestepping most
of this session's HSV-tuning fights.
**Caveat that must be handled for this to actually work, not just relocate the problem**: the
two-dimple issue doesn't go away by flipping colors alone — if the non-marker dimple is left as
plain puck material, it's still a second dark/recessed feature, now specifically resembling
what the flipped scheme is hunting for (a dark spot on a colored disk). The non-marker dimple
needs to stop being a distinct candidate at all: paint it to match the disk body (visually
disappears against the now-colored surface) or fill/smooth it flush. The marker dimple should
be the disk's *only* non-disk-colored feature, and ideally a deliberately strong, unambiguous
one (paint it black, not just bare/natural material) rather than something that could itself
pick up a color cast under certain lighting.
**Pipeline implication if this is adopted**: `resolve_marker_color`'s whole approach (search a
padded crop for a small colored blob) inverts — disk *identity* would come from color-matching
the bulk of the bbox/disk area (a much easier, more robust version of what `GREEN_LOWER/UPPER`
already do), and the *marker* search becomes "find the darkest/least-saturated region within
the now-reliably-colored disk," structurally different from anything currently in
`Pre_process.detect_marker_center`. Real implementation work for whenever new footage using
this scheme exists — not attempted yet, no code changed for this.

**Paint spec, if repainting** (user decided marker dimple = black; this covers the disk body):
- **Finish: matte/flat, no exceptions.** Direct fix for this session's #1 recurring root cause
  — glossy finishes create specular highlights (bright, desaturated, move with rotation) that
  repeatedly got confused with the real marker, worst on the current glossy blue marker
  specifically. Avoid gloss/satin/semi-gloss, and *especially* metallic/pearlescent/duochrome
  finishes (mica/flake scatters many small specular points — worse than plain gloss).
- **Paint type: spray, formulated for plastic, not craft/"aqua" acrylic.** These disks take
  repeated impacts by design (it's a collision study) — hand-applied acrylic chips more easily
  under that than a proper "for plastic" spray enamel (etches/bonds without a separate primer,
  flexes with the substrate instead of cracking). A matte clear topcoat once cured adds
  abrasion resistance and locks in the flat finish against handling wear.
- **Colors: stay in the green/blue family** (well-separated from the table's white/red on the
  color wheel — no reason to change what already works there) **but aim for true, saturated
  mid-tones**: kelly/emerald green, royal/cobalt blue. Avoid pastels and white-adjacent colors
  (disappear into glare-washed table), red/orange (matches the table's own graphics), navy
  (too close to the black marker's value), and fluorescent/neon pigments (tend to clip/bloom a
  camera's color channel under bright light, fighting HSV calibration).
- **Test one disk first**: paint a single sample, let it cure, check it under real lab lighting
  with the camera before committing the full set — cheaper than repainting twice, given how
  often real footage has contradicted expectations on this project.

**Goal**: fill the whole rotation column (every frame gets a usable angle), via recall
improvements *and* physics-based recovery/interpolation, not recall alone.

**This is the plan for the next session** (nothing below has been implemented yet — tonight
was diagnosis + the two contour-selection fixes above):

0. ~~**First thing next session**: RANSAC/sigma-clipping step 2 below will itself flag frames
   like `240_25.mp4` frame 368 as trend-inconsistent outliers once it's built.~~ **Done, and the
   prediction was half right** — built and real-footage-validated (see Known bugs #1 update);
   it does flag real bad frames (caught the newly-found 397/399/401 color-misread frames in the
   same clip) but did *not* catch frame 368 specifically, because that frame sits in an
   unusually corrupted real window (~36% of nearby detections inconsistent with any single
   trend — see Known bugs #1 for the full breakdown), well beyond anything a single global
   per-segment linear fit can be expected to resolve alone. Downgraded from "bug 1 doesn't need
   its own fix" to "bug 1 likely needs step 3 (physics-assisted recovery) and/or better
   marker-localization precision, not a smarter fit on the same noisy per-frame reads."
1. ~~Segment each disk's timeline at the collision frame...~~ **Done** —
   `Post_process.fit_rotation_segments`/`fit_rotation` split at `_find_collision_frame` into
   "before"/"after"/"collision" (excluded from fitting), never fit across the boundary.
2. ~~Robustly fit angular velocity per segment...~~ **Done** —
   `Post_process._robust_unwrap_and_fit` (called per-segment by `fit_rotation_segments`).
   Turned out plain "sequential `np.unwrap` then sigma-clip" isn't safe on its own: a single bad
   marker value landing near the +-180 deg branch cut can flip which 360 deg branch sequential
   unwrap locks onto for *every later sample*, so a naive pipeline's sigma-clip never sees an
   outlier — it sees a uniformly-shifted trend instead (reproduced on synthetic data: one
   injected bad point flipped a fitted omega's sign and changed its magnitude by ~2.5x). Fixed
   by choosing each sample's 2π branch relative to a robust linear *prediction*
   (`_robust_omega_seed`, a median of nearby wrapped pairwise slopes — deliberately never runs a
   global sequential unwrap at all) instead of relative to the previous raw sample, refined over
   a few rounds together with the sigma-clip fit. Validated: 400/400 synthetic trials (0-3
   injected bad points per ~100-250-point segment, 30-95% recall) recovered true omega within
   0.15 deg/frame; on real `240_25.mp4` footage, a clean window (disk 1, frames 672-857) fit
   with zero flagged outliers at omega=0.76 deg/frame (in line with the ~1 deg/frame
   expectation); a corrupted window (disk 0, frames 365-591, containing frame 368) correctly
   flagged 51/141 marker detections as outliers including the newly-found 397/399/401 color
   misreads, but not frame 368 itself — see Known bugs #1 for why. **Not yet wired into
   `_compute_metrics`'s energy calc** (roadmap item 0.3) or into CSV export/`theta_source`
   (steps 3-5 below, not started).
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

## Pre-repaint roadmap (ordered — goal: only HSV tuning left once new footage exists)

**Context**: user is repainting the disks (whole disk colored, black marker dimple — see
"Design idea" in the Rotation/marker plan above) but can't do that or shoot new footage until
back in the lab, ~2 weeks out (target: **2026-08-30**). Everything below is scoped to be
buildable and testable *now*, against current footage, so that when new footage exists the
only remaining step is retuning HSV constants — not writing new logic. Ordered by dependency;
do not reorder without a reason (later items build on earlier ones being correct).

### 0. Physics-metrics review (found tonight, do first — everything downstream depends on
   trustworthy kinematics)

Reviewed `_compute_metrics`/`_compute_vels`/`_unwrap_angle` (`Post_process.py`) end-to-end, the
restitution/momentum-error/energy-drop calculations the user asked to have reviewed. The
restitution and momentum-error *formulas* themselves are correct (line-of-centers projection,
standard `e = v_n_after/v_n_before`, standard `Δp/p`), and the energy calc's use of **median**
ω per segment (already robust to outliers) rather than mean was a reasonable existing choice.
But two real, previously-undocumented correctness bugs surfaced, both upstream of the formulas:

1. **`_unwrap_angle`/`_compute_vels` (`Post_process.py:47-71`): a single missing marker
   detection poisons every later frame in that segment, not just that one frame.**
   `np.unwrap` does not skip `NaN` — verified this session:
   `unwrap([0,-1,-2,NaN,-4,-5,-6]) == [0,-1,-2,NaN,NaN,NaN,NaN]` (deg). `mx_mm`/`my_mm` land as
   `NaN` whenever `resolve_marker_color` fails for a frame (rows are still written for the
   disk, just with empty marker cols — see `detector.py:576-581`), and neither
   `_unwrap_angle` nor `_compute_vels` filters/interpolates before calling `np.unwrap`. Given
   documented marker recall is only ~44-60%, most before/after segments almost certainly hit
   their first gap early, meaning `theta_unwrapped_deg`, `omega_deg_s`, and the energy-drop
   metric are likely running on far less real data than they appear to (silently `NaN` past
   the first gap, or a median computed over a tiny surviving prefix) — independent of the
   recall problem itself and not something the rotation-recovery plan below fixes on its own
   (that plan adds new theta values; it doesn't stop a stray `NaN` from poisoning the raw
   unwrap it still runs first). **Fix**: mask/interpolate `NaN` rows out before unwrapping (or
   unwrap only the contiguous run of non-`NaN` values), not after.
2. **`_compute_vels`'s `vx`/`vy` (`Post_process.py:60-61`) assume every row is exactly one
   frame apart.** Confirmed in `detector.py:568-589`: a disk gets **no row at all** for a frame
   where it wasn't detected (no `NaN` placeholder, the row is simply absent) — YOLO position
   tracking is "near-perfect" per the Model section but not literally 100%, so gaps do happen
   occasionally. `.diff() * fps` doesn't know about the gap and silently overstates velocity by
   the gap size whenever one occurs, feeding directly into restitution and momentum error (and,
   via `Vcm`, into the COM-frame energy calc's translational term too). **Fix**: divide by
   actual `Δframe * (1/fps)`, e.g. `out["frame"].diff()` as the denominator instead of assuming
   1.
3. **Once item 4 below (RANSAC ω fit) exists, wire its per-segment ω into `_compute_metrics`'s
   rotational KE term (`Kr0b`/`Kr1b`/etc., `Post_process.py:190-193`) instead of the raw
   per-frame `omega_deg_s` median.** The median is already robust to gaps but not to
   *wrong-but-plausible* values like the known `240_25.mp4` frame 368 false positive (a
   confidently-wrong value, not a gap — see Known bugs below) — a trend-fit ω rejects that
   structurally, a per-frame median doesn't. Low priority relative to 1-2 (which are outright
   bugs); this is a quality improvement, sequence it after item 4 exists.
4. Not a bug, just noted for completeness: `RADIUS_M` (`Post_process.py:145`) averages both
   disks' measured radii for both disks' inertia. Given both disks are the same nominal 70mm
   spec, this is probably *more* robust than each disk's own noisier estimate, not less — no
   change proposed, flagging only so it's a documented decision rather than an oversight if
   revisited later.

### 1. Independent tracking bugs (Known bugs #2, #3 below) — cheap, foundational, unrelated to
   paint scheme

**Done** — see Known bugs #2 (`IDAssigner` velocity-gated lock) and #3
(`estimate_background_median` puck masking) above for full detail and validation. Both are
scheme-agnostic robustness fixes, still useful unchanged after repainting.

### 2. Rotation/marker recovery plan — steps 1-2 only (segmentation + RANSAC/sigma-clipping ω
   fit + outlier flagging)

**Done** — see "Rotation / marker detection — live plan" steps 0-2 above for full detail and
real-footage validation results (400/400 synthetic trials clean; real clean window fit
perfectly; real corrupted window correctly flagged 51/141 outliers, including newly-found
frames, but not frame 368 specifically — that's now understood as a window-corruption-level
issue, tracked under Known bugs #1, not a step-2 gap).
Scheme-agnostic: operates on whatever theta values the detector produces, old paint or new.

### 3. Rotation/marker recovery plan — steps 3-5 (physics-assisted recovery search,
   interpolation fill, `theta_source` column)

Only after item 2 is validated. Also scheme-agnostic — reusable unchanged after repainting.

### 4. Build the whole-disk-color detection path now, gated behind a flag, HSV constants as
   placeholders

This is the piece that actually delivers "just tune HSV once new footage exists":
- New identity path: match the *bulk* of the bbox/disk region to green/blue (easier, more
  robust version of what `GREEN_LOWER/UPPER` already do against a small marker blob).
- New marker path: search for the *darkest/least-saturated region* within the now-reliably-
  colored disk (structurally different from `Pre_process.detect_marker_center`, which hunts
  for a specific saturated hue).
- Keep the current `resolve_marker_color`/`detect_marker_center` path fully intact and reachable
  — gate the new path behind a config flag/param so existing footage (old paint scheme) keeps
  working unchanged. Do not delete or replace the old path.
- **Be honest about the limits of building this blind**: unlike items 1-3, there is zero real
  footage of the new scheme to validate against yet, so "just tune HSV" is the goal, not a
  guarantee — some structural bugs may only surface once real painted footage is seen. Building
  it now still front-loads all the *design* risk (function shape, where identity vs. marker
  logic lives, integration with `IDAssigner`) so that whatever's left when footage exists is as
  close to HSV-only as achievable.

### 5. Long-tail, low priority, independent of everything above (from "Long Term Issues")

- ~~Suppress/fix the Windows DPI-awareness warning.~~ **Done** (side quest, done alongside item
  2 below — see Long Term Issues section for root cause).
- Add a progress/loading indicator between hitting "generate" and the preview being ready.

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

- ~~Correct the DPI warning.~~ **Done** — root cause was `app.py` manually calling
  `ctypes.windll.shcore.SetProcessDpiAwareness(2)` *after* PyQt6 was already imported (PyQt6
  imports at the top of the file had already triggered Qt6's automatic per-monitor-v2 DPI
  awareness — the manual call was a leftover Qt5-era workaround, no longer needed in Qt6, and
  Windows only allows setting process DPI awareness once, so the redundant call is what
  produced the warning). Removed the manual call entirely.

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
