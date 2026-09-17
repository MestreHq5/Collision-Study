# ToDo — Detection approach for the repainted disks

> Written after actually re-running both branches against `Video11.mp4` myself
> (not taking the "main won" report on faith) to find out *why* main won, and
> whether that reason will still apply once the disks are repainted. Numbers
> below are real, from this session, not estimates.

## 1. What I tested

Ran both branches' full `detector.main()` + `Post_process._compute_metrics()`
pipeline against `C:\Users\gonca\Pictures\Camera Roll\OLD\Video11.mp4`
(1920x1080, 54.89 fps container, 289 frames) — checked out `main` into a
throwaway worktree so I could run it side by side with `deepLearning` (this
branch) without touching your working tree.

| | `main` (classical contour) | `deepLearning` (YOLO + classical marker) |
|---|---|---|
| Detections written | 90 rows (44 + 46), frames 133–181, near-contiguous | 78 rows (35 + 43), frames 140–183, gappy |
| Raw YOLO recall (all 289 frames, checked separately) | n/a | **0 disks in 240/289 frames (83%)**, both disks in only 38/289 (13%) |
| Raw YOLO radius (median, all detections) | n/a | 11.4 px (range 10.0–13.2) |
| Computed scale | 0.743 mm/px (matches contour radius ~54px) | **3.262 mm/px — 4.4x off from main's** |
| marker_color recall | 100% / 100% | 60% / 46.5% |
| Collision frame | 145 | 148 |
| Restitution e | **0.9485** | NaN |
| Momentum error (rel.) | **7.14%** | NaN |
| Energy drop, COM frame | **4.85%** | NaN |

`deepLearning`'s metrics are `NaN` because YOLO essentially didn't see disk 0
during the approach — only 1 frame before the collision vs. 33 after — so
there's no "before" velocity to compute restitution/momentum from at all.
This is not a rounding or noise issue, it's a near-total detection failure on
this footage.

## 2. Why main actually won — this is a domain-shift bug, not a verdict on YOLO

The deployed model (`runs/pose/train-5/weights/best.pt`) was trained
exclusively on `Novos Videos` — new-lab footage, new camera framing, the old
gray-body/tiny-dot disks. `Video11.mp4` is old footage: different lab,
different camera distance/framing, filmed before any of that training data
was collected. The model was **never going to generalize** to it, and the
numbers confirm a hard failure, not a soft one: 83% zero-disk frames, and
even the rare hits have boxes ~4-5x too small (11px vs. the disk's real ~54px
contour radius on this footage).

So "main worked better on Video11" is real and reproducible, but it doesn't
mean classical CV beats YOLO in general — it means **this specific YOLO
checkpoint is useless outside the footage it was trained on**, which was
already true in principle and is now true in measured numbers. It also
doesn't contradict CLAUDE.md's earlier "settled" conclusion that classical
contour failed under the *new lab's* glare and YOLO didn't — that test was
run on new-lab footage, this one wasn't. Both findings are correct in their
own domain. The lesson that actually generalizes: **whichever detector you
use has only ever been validated on the footage it was tuned/trained
against** — nobody has an approach validated against real painted-disk
footage under real shooting conditions, because that footage doesn't exist
yet.

## 3. What this means for the repaint — three real options, not two

The repaint changes the target from "small, near-black, low-saturation dot
on a gray disk" to "the whole disk is a large, saturated, matte color." That
changes the calculus for classical CV specifically — it was never the
*disk position* that classical CV struggled with under decent lighting (see
main's clean 7% momentum error here), it was the marker. A bigger, more
saturated target is strictly easier for contour/color work regardless of
which lighting you shoot under.

**Option A — Position via color contour, not background-subtraction (new code, ~half a day).**
Segment disks directly from an HSV mask of the union of the calibrated
green/blue ranges (contour + `minEnclosingCircle`, same gating as
`segment_disks`), instead of frame-differencing against a background image.
`Pre_process.py` doesn't have this function yet — `classify_disk_bulk_color`
assumes you already know disk_center/radius, it doesn't find them. This
sidesteps *both* failure modes seen so far: no YOLO domain-shift risk (no
model at all), and no background-subtraction fragility (doesn't care if a
puck was sitting on the table during the "clean" background window, doesn't
care about frame-to-frame lighting drift the way a fixed `thresh_val=50`
diff does). Matte finish also directly helps this approach specifically,
since specular glare is what blows a saturated color out toward white and
breaks HSV thresholding.

**Option B — Keep YOLO for position, only retune the marker scheme (current architecture, no new code).**
This is what `MARKER_SCHEME = "flipped"` already exists for. Cheapest in
engineering time, but it inherits the exact risk that just bit us: YOLO's
box has never been validated against what a repainted disk actually looks
like (the training images are all gray-body pucks — full-color disks are a
real visual distribution shift), and the CLAUDE.md-documented "bbox radius
noisy, underestimates by >3x" bug is now confirmed severe on mismatched
footage. Don't assume it'll just work; it needs the same kind of check this
session just did, on real painted-disk footage, before you trust it.

**Option C — Pure classical, background-subtraction position (what main already does) + `"flipped"` marker scheme's dark-dimple logic reused for the whole-disk color instead.**
Cheapest of all (main's `segment_disks` already works, per this test), but
inherits classical CV's one *confirmed* real weakness: glare under the new
lab's overhead LEDs broke it before, independent of the marker problem. If
the new footage is shot under that same lighting, this option carries that
risk forward untested.

## 4. Recommendation

**Don't lock in an approach from this test — it answered "why did main win
on Video11", not "what wins on the new disks."** The one thing every option
above shares is that none of them has been run against a single real frame
of a painted disk. That test is cheap and is already called for in
CLAUDE.md's own paint spec ("test one disk under real lab lighting before
committing the full set") — do it before writing more pipeline code, not
after.

Concretely, once you have **one** painted disk:
1. Shoot a short clip under whatever lighting you actually intend to use for
   real runs (new lab, LEDs on, as realistic as possible — not a
   convenient desk lamp test).
2. Run three quick checks against it, reusing the comparison harness from
   this session (I can rebuild it in ~5 min):
   - Raw YOLO detection recall + box radius sanity (`detect_disks_yolo`
     directly, frame by frame) — is the box even close to the true 35mm
     radius now, on a full-color disk?
   - `segment_disks` (background-subtraction contour) recall under that
     lighting — does the new lab's glare still break it, now that there's
     no tiny marker to lose, just a big saturated blob?
   - A quick HSV mask of the disk's paint color, visually inspected — does
     glare blow out the saturated color, or does the matte finish actually
     fix it like the paint spec assumes?
3. Whichever position method survives that real test wins. Don't extrapolate
   from Video11 (wrong domain for YOLO) or from the pre-repaint Novos Videos
   tests (wrong marker scheme, not yet the real paint) to make this call —
   both of those are exactly the mistake that made this test necessary.
4. My honest lean, *conditional on the lighting turning out glare-prone
   again*: Option A (color-contour position) is worth building first — it's
   new code but not much of it, it removes the domain-shift risk entirely
   (no model in the loop at all), and it's the option best matched to what
   the repaint specifically changes (small unreliable marker → whole disk
   is now the signal). If the lighting genuinely isn't glare-prone this
   time, don't build Option A at all — just reuse main's classical pipeline
   as-is with the flipped/whole-disk color logic swapped in, it's already
   proven clean at 7% momentum error and needs zero new detection code.

## 5. 2026-09-17 update — Option A tested against real painted-disk footage, and it wins

Three real webcam clips of the repainted disks now exist
(`C:\Users\gonca\Pictures\Camera Roll\New Disk Tests\`: `Previous_Side_Light.mp4`,
`Previous_Side_No_Light.mp4`, `Other_Side.mp4`). Ran the actual comparison this file called
for in section 4:

- **YOLO (`train-5`) on the new painted disks**: confirmed hard failure, same shape as the
  Video11 result above but now on the actual target footage — boxes 4-5x undersized
  (~10-14px vs a real ~40-66px), confidence 0.05-0.25 (mostly below the pipeline's own 0.10
  threshold), only 0-12 frames per clip with both disks detected simultaneously.
- **Option A (color-contour position, `cv2.inRange` + contour + `minEnclosingCircle`, no
  model)**: tested with the retuned `FLIPPED_GREEN/BLUE_LOWER/UPPER` ranges. Within each
  clip's actual "both disks on table" window: **78% (Previous_Side_Light), 0%
  (Previous_Side_No_Light — see below), 92% (Other_Side)** of frames had both disks detected
  simultaneously — vs. YOLO's low single digits over the same footage.

**Verdict: Option A is the one to build now.** The whole-disk paint makes this the easy case
Option A was written for — a big, saturated, matte blob is exactly what color-contour is
good at, and it completely sidesteps the domain-shift risk that keeps burning YOLO on
anything outside its exact training distribution. Recommend deprioritizing YOLO
retraining/annotation until Option A is built and tested more broadly — it may make the
retrain unnecessary for position detection entirely (YOLO would only still matter as an
optional fallback, e.g. a frame where color contours fail).

**Lights-off is bad for this paint, opposite of the old marker-scheme finding**: 0% green
recall in `Previous_Side_No_Light` (0/374 frames matched the green range at all, even with a
broad initial hue/sat net during calibration) — this specific "army/olive" green paint reads
as desaturated grey/white without the overhead light, dropping below any reasonable
saturation floor. The old classic-scheme finding ("lights off helped marker recall") does NOT
carry over to the flipped scheme's bulk-color detection — that finding was specific to
reducing glare on a tiny marker dot, not to this paint's saturation under low light.

**Regular side (lit) vs. other side**: other side measured higher recall (92% vs 78%), but
it's confounded (different throw each time) and the other side has real physical downsides
the user flagged: cramped space (disks bounce off the boundary and need manual video
clipping), and collisions forced slower/less natural because the throw distance to the
collision point is short. Leaning toward: **regular side, lights on, as primary** — plausibly
losing recall specifically because the overhead glare band sits near the mid-table collision
zone (visible in raw frames); worth testing a small camera/table reposition on the regular
side to dodge that band (cheap, keeps full throw distance) before conceding recall to the
cramped alternate side. Other-side footage still useful as supplementary training diversity,
not as the primary experimental setup.

## 5b. Option A built and run end-to-end (`color-thresholding` branch)

Implemented as `Pre_process.segment_disks_by_color()` + `detector.detect_disks_color()`,
wired in as `main()`'s primary position detector (replacing `detect_disks_yolo()` on this
branch only — `deepLearning` is untouched). Ran the real `build_student_excel(...,
include_metrics=True)` physics pipeline against the actual CSV output, not just detection
recall:

- **`Previous_Side_Light`**: clean, physically plausible result — e=0.898, momentum error
  5.6% (rel.), energy drop 23% (COM frame). Same ballpark as `main`'s old classical result on
  Video11 (e=0.9485, 7.14%) — real end-to-end validation, not just a recall number.
- **`Other_Side`**: garbage — e=-0.435 (unphysical, implies the disks were approaching after
  the "collision"), momentum error 86.6%, energy drop NaN. **This is not a color-thresholding
  failure** — it's the boundary-bounce problem the user already flagged (section 7 action
  item): that clip has more than one contact event (wall bounce), which breaks
  `_find_collision_frame`'s single-collision assumption and poisons the before/after velocity
  segments it depends on. Confirms manual clipping of `Other_Side`-style footage isn't
  optional busywork — uncut, it produces confidently-wrong physics, not just noisier numbers.
- `Previous_Side_No_Light` skipped — disk 0 (green) has zero detections in that clip (see
  section 5), so there's no "before" track to compute anything from at all.

## 6. Minor bug found along the way

`main`'s `detector.py` hardcodes `DISK_DIAMETER_MM = 80.0`; this branch
(and CLAUDE.md, user-confirmed) uses `70.0`. Doesn't affect the
momentum-error comparison above (it's a dimensionless ratio, a wrong global
scale cancels out), but it means main's absolute mm/velocity numbers in any
exported CSV/Excel are ~14% off from physical reality. Fix if main's
pipeline (or Option C/the old marker-search code it contains) gets reused
for the new disks.

## 7. Open action items

- [ ] **Manually clip `Other_Side`-style videos before detection.** That side of the table is
  cramped enough that disks bounce off the boundary and come back — the pipeline expects one
  clean approach/contact/separation per video (see CLAUDE.md "Filming pattern"), so any clip
  shot on that side needs the post-bounce tail (and any pre-bounce noise) trimmed out by hand
  first. Not an issue for the regular side's normal throws.
