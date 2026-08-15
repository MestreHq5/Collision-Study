# Collision-Study (DEM) — Project Context

> This file is read automatically by Claude Code at the start of sessions in this repo.
> Keep it updated as the project evolves — add new bugs, remove resolved ones, log decisions.

## What this is

Python/PyQt6 desktop app that analyzes 2D collisions of two circular pucks on an air table
from video footage, tracking position/orientation/kinematics per frame and exporting
scaled physical metrics (mm, s) to CSV for Discrete Element Method (DEM) validation.

- Disk 0 = Green marker, Disk 1 = Blue marker
- Disk diameter: 80.0 mm, default mass: 0.0118 kg
- Disk **bodies** are gray/slate — only a small offset marker dot on the surface is colored. This is usefull to track rotation.
  This matters: any detection logic that assumes the whole disk is colored will fail.

## Architecture

```
Collision-Study/
├── initializer.py    # Entry point; sets Windows DPI awareness BEFORE Qt import
├── app.py             # PyQt6 GUI (file selectors, FPS inputs, process triggers)
├── helper.py          # Bridges GUI calls to backend pipeline
├── detector.py        # Core pipeline: video I/O, detection, ID tracking, CSV export
├── Pre_process.py     # CV utilities (HSV filtering, marker isolation, background estimation)
└── runs/pose/train-5/weights/best.pt   # Fine-tuned YOLO Pose model (best run to date, in use)
```

Single active branch now: **`deepLearning`** (the older `contour` / `yolo-pose` branch split
described in earlier notes no longer exists in this repo — both approaches now live together
in `detector.py` on `deepLearning`, as a hybrid, not as separate branches).

`detector.py` detection pipeline (as of this session):
- **Primary: YOLO Pose** (`runs/pose/train-5/weights/best.pt`, single class `puck`, 2
  keypoints `[center, marker]`) — `detect_disks_yolo()`. Disk center prefers the "center"
  keypoint (falls back to bbox center if low-confidence); radius comes from the bbox.
  `conf=0.10` (see conf discussion below), `imgsz=1280` (matches training `imgsz`, see
  `runs/pose/train-5/args.yaml`). `remove_duplicate_detections()` dedupes boxes within 30px,
  keeping the higher-confidence one.
- **Marker color**: `resolve_marker_color()` scans the whole disk ROI first
  (`prp.detect_marker_center` on bbox-derived center/radius), falling back to a tight
  keypoint-anchored search only if that fails (this order was flipped in an earlier session).
  Matches are gated by `MARKER_MIN_AREA_FRAC`/`MARKER_MIN_CIRCULARITY` (a real paint marker is
  a compact round blob; rejects thin rim/shadow slivers at comparable area) and by
  `MARKER_MASK_PAD_MULT` (the "must be inside the disk" mask always uses the disk's real
  center/radius — padded 1.4x, since the offset marker sits near the true edge — never the
  search anchor itself, so an unreliable keypoint anchor can't leak the search into
  background). `detect_marker_center`'s CLAHE tile grid and morphological kernel both scale to
  the actual crop/disk size rather than fixed pixel constants — both were found to silently
  break (manufacture false color / erase real markers) on footage with a different object
  scale than whatever they were last tuned against. See Crucial Section log for the concrete
  measurements behind these.
- **Fallback: background-subtraction contour** (`fallback_contour_disks()`) — only triggers
  when YOLO found fewer than 2 disks in a frame, and only searches within
  `FALLBACK_SEARCH_RADIUS_PX` (250px) of a missing disk's last known position
  (`assigner.prev_pos`), not the whole frame. Candidates are also gated by radius (0.5x–1.8x
  of a reference radius — this frame's other YOLO disk if there is one, else the calibrated
  disk radius derived from `scale_mm_per_px`) so an oversized glare/reflection/motion-blur
  blob can't slip through just because it's circular.
- **ID logic**: `IDAssigner` — **position-lock now runs before color** (a detection within
  `POSITION_LOCK_GATE_PX` (60px) of an already-tracked ID's last position claims that ID
  immediately); color-first assignment only decides identity for detections that don't match
  an existing track (new arrivals, or gaps beyond the lock gate); unbounded nearest-neighbor
  and deterministic left-right fallback remain as before for what's left. This priority flip
  was the key fix this session — see bug log. Note: this is a plain class, not a
  `PersistentDiskTracker` — that name from earlier notes never actually existed in this
  codebase.

## Hardware / lab history (important — explains why YOLO exists)

1. **Old lab, webcam, 60fps, natural light** — classical CV (`contour` branch) worked well.
   Some motion blur was present but didn't break detection.
2. **New lab, same webcam** — artificial lighting + glare directly on the table surface
   broke classical detection (background subtraction / HSV thresholds no longer reliable).
3. **New lab, phone camera** (sharper image, effectively no motion blur) — classical CV
   *still* underperformed here, even without blur. This is the key signal: the new lab's
   glare/lighting is the actual problem, not camera shutter or blur. This is what motivated
   the switch to YOLO.
4. Phone camera is the likely long-term choice (better image quality) but not finalized.
   FPS choice (60 vs 240) also undecided — pipeline should stay FPS-agnostic
   (`fps_eff` param) so both can be benchmarked once tracking is stable.

**Working theory, now partially confirmed:** the new lab's glare is a genuine
lighting/reflection problem, not primarily an exposure/shutter issue. With `train-5` wired
into `detector.py` and smoke-tested end-to-end against two real new-lab clips (`NL01.mp4`,
60fps, and `240_25.mp4`, 240fps — see below), the picture is more nuanced than "recall is
low": **once a puck is actually in frame, YOLO position/box detection is excellent** — dense
frame-by-frame checks on `240_25.mp4` showed continuous detection with zero internal gaps
during all three puck passes (only misses were frames before/after the puck entered/left this
tightly-cropped phone shot, which is a filming-setup fact, not a model failure), including 32
straight frames of both disks tracked simultaneously through the actual collision. The
low-recall numbers seen on `NL01.mp4` are real but conflate "puck not visible this frame" with
"model missed a visible puck" — a naive frames-with-detection ratio undercounts accuracy when
much of a clip has no puck on screen at all. Bottom line: box/position detection is close to
solved; **marker color detection is the fragile part** (see bugs below), not YOLO itself.

## Known bugs / open issues (as of Aug 2026)

### Fixed this session (240_25.mp4 smoke test)
1. **`cv2.VideoWriter` silently produced a 0-byte `detection.mp4` for real camera FPS values**
   (e.g. `240.10231632798067`) — the float has enough precision that mpeg4's timebase
   denominator overflows its 65535 max and the writer fails to open, with no exception raised
   (`out.write()` no-ops for the whole run). Fixed by rounding fps to 2 decimals for the
   writer only (`round(fps, 2)`) — `dt`/`fps` used for physics stay full precision. Only
   surfaces with 240fps-class footage; 60fps/30fps values were clean enough to not trigger it.
2. **`GREEN_UPPER`'s S/V ceiling (was 88/129) rejected this footage's true marker pixels
   outright** (measured median ~S214/V92, p99 ~S237/V139) — it was tuned for dimmer footage.
   Widened; see the HSV constants' comments in `detector.py` for the measured values.
3. **The YOLO "marker" keypoint is not reliable for color** — measured on real footage this
   session, it lands on a non-marker specular highlight on the glossy disk body ~44% of the
   time (the highlight moves with disk rotation too, same as the real marker, so the model
   confuses them). Fixed by making `resolve_marker_color()` scan the whole disk ROI *first*
   (keypoint-independent — finds the largest matching blob anywhere on the disk) and only
   fall back to the keypoint-anchored tight search second.
4. **CLAHE's fixed `tileGridSize=(8,8)` on a marker-sized crop (~roundabout the disk's own
   size) gave tiles only a few px across** — too small a sample for local histogram
   equalization, so it was manufacturing fully-saturated fake "color" out of sensor noise on
   the flat gray disk body instead of just rescuing a dim real marker. Fixed in
   `Pre_process.detect_marker_center` by scaling `tileGridSize` to the ROI's actual pixel
   size (min ~16px/tile).
5. **The biggest one: a single spurious color match could steal an already-tracked disk's
   identity.** `IDAssigner`'s old color-first-then-position order meant one bad HSV hit on the
   wrong disk (from bug 3/4 above, or just marker-visibility noise) would immediately
   reassign that disk's `disk_id` for that frame, then flip back next frame — a single
   physical puck's trajectory split frame-by-frame across `disk_id` 0 *and* 1, repeatedly,
   for an entire pass. **Fixed by flipping the priority: position-lock (tight 60px gate to an
   ID's last known position) now runs before color.** Validated on the full 240_25.mp4 run:
   zero identity flip-flops anywhere in the video, zero consecutive-frame position jumps
   >60px, both known single-puck passes stayed 100% on one `disk_id` throughout. Color
   coverage in the CSV *dropped* as a side effect (fewer frames get a `marker_color` value,
   since position now wins whenever there's an established track to match) — that's fine and
   expected: color's only remaining job is to identify genuinely *new* tracks, and its
   occasional wrong answers can no longer corrupt an established one.

Net effect of 2-5: marker color detection is still imperfect (a real HSV/CV limitation — small
marker, glossy/highlight-heavy blue paint, tiny search ROIs) and this wasn't and can't fully be
"solved" by threshold tuning alone. What matters for correctness is bug 5's fix: the pipeline
is now **robust to color being wrong or absent**, which is what actually gets validated to
near-perfect position/identity tracking on real footage.

### Still open
6. **`IDAssigner`'s step-3 nearest-neighbor (for detections beyond the position-lock gate)
   still has no maximum distance check** — relevant for a disk reappearing after a multi-frame
   gap. Directive 3 (velocity-gated lock) would replace both this and the static
   `POSITION_LOCK_GATE_PX`/`FALLBACK_GATE_PX` gates with a motion-extrapolated one.
7. `estimate_background_median()` (used both for scale calibration and as the contour
   fallback's background reference) assumes the first `CLEAN_SECONDS` of video has no pucks
   on the table. If a puck is already in frame at t=0, background estimation — and therefore
   `scale_mm_per_px` and every contour fallback for the rest of the run — is degraded.
8. HSV calibration (`GREEN_LOWER/UPPER`, `BLUE_LOWER/UPPER`, `MARKER_MIN_AREA_FRAC`,
   `MARKER_MIN_CIRCULARITY`) was tuned against exactly one clip (`240_25.mp4`). Treat as a
   reasonable starting point, not a universal calibration — re-validate (or rerun
   `prp.calibrate_hsv_range`) against new lighting/exposure setups.

## Directives (carried over from original briefing)

1. ~~YOLO detection filtering: keep `conf` around 0.10–0.15, dedupe candidate boxes via
   distance threshold.~~ **Done** (`YOLO_CONF=0.10`, `remove_duplicate_detections`, 30px —
   0.10 chosen after an A/B sweep on real footage showed it recovers frames 0.15 misses with
   zero measured false positives in puck-free stretches of the same video).
2. ~~Motion/background fallback only in expected disk regions when YOLO detects <2 disks,
   rather than discarding the frame.~~ **Done** (`fallback_contour_disks`, gated by both
   position — near `prev_pos` — and radius).
3. **Partially done:** Trajectory-based persistent ID lock — `IDAssigner` now does
   position-lock-before-color (see bug 5 fix above), which is a fixed-distance gate, not the
   originally-specified velocity-extrapolated one. Still open: replace
   `POSITION_LOCK_GATE_PX`/`FALLBACK_GATE_PX` with linear extrapolation from the last 2-3
   known positions, which would also fix bug 6 above and let the fallback search from a
   *predicted* position instead of a stale last-confirmed one after multiple missed frames.

## Suggestions for next session

- Implement the velocity-gated lock (directive 3) — this is now the main remaining piece of
  the original briefing, and would tighten both `IDAssigner` and the contour fallback's search
  center in one change.
- If pursuing further training-data augmentation for YOLO: prioritize *marker visibility/color*
  variety (angles, lighting, motion blur) over raw puck-detection frames — bug log above shows
  box/position detection is already strong; color is the weaker link.
- Local new-lab test footage (not checked into the repo — `Videos/` was cleared out) lives at
  `C:\Users\gonca\Pictures\Camera Roll\NL\` (60fps) and `...\Camera Roll\Novos Videos\` (240fps,
  e.g. `240_25.mp4` used this session) — use these for future smoke tests of `detector.py`
  instead of hunting for videos elsewhere. Note: `...\Camera Roll\Novos Videos\240_1.mp4` (and
  likely some neighboring files) is an unrelated air-hockey-table clip, not this project's rig.
- Once tracking is stable, benchmark 60fps vs 240fps footage on tracking continuity and CSV
  completeness to make the FPS decision.


## Crucial Section (User Assigned Missions)

The tasks on this section take priority over any others. If this section is not empty or marked as done please start with the problems state here. Once a problem or set of problems here are done, please step aside for the user to make a manual run on the program and confirm problem resolution. Mark them with "*Done*" at the beginning of the problem once resolved.

- *Done* PS C:\Users\gonca\Desktop\Collisions DEM\Collision-Study> & C:\Users\gonca\AppData\Local\Programs\Python\Python311\python.exe "c:/Users/gonca/Desktop/Collisions DEM/Collision-Study/initializer.py"
[INFO] App Starting
setHighDpiScaleFactorRoundingPolicy must be called before creating the QGuiApplication instance
qt.qpa.window: SetProcessDpiAwarenessContext() failed: Acesso negado.
Qt's default DPI awareness context is DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2. If you know what you are doing, you can overwrite this default using qt.conf (https://doc.qt.io/qt-6/highdpi.html#configuring-windows).
[INFO] Video Selected: C:/Users/gonca/Pictures/Camera Roll/Novos Videos/new01.mp4
[INFO] Video Native FPS: 57.00031786566674
[Done] Background Averaged
[Info] YOLO Pose model loaded (best.pt) on device=0
[Info] File Container Native FPS: 57.00
[Info] Per frame time: 0.0175s
[Info] Computed scale: 3.850 mm/px
[Done] Saved 46 detections to disk_tracks.csv
C:\Users\gonca\AppData\Local\Programs\Python\Python311\Lib\site-packages\numpy\lib\nanfunctions.py:1215: RuntimeWarning: Mean of empty slice
  return np.nanmean(a, axis, out=out, keepdims=keepdims)
C:\Users\gonca\AppData\Local\Programs\Python\Python311\Lib\site-packages\numpy\lib\nanfunctions.py:1215: RuntimeWarning: Mean of empty slice
  return np.nanmean(a, axis, out=out, keepdims=keepdims)
C:\Users\gonca\AppData\Local\Programs\Python\Python311\Lib\site-packages\numpy\lib\nanfunctions.py:1215: RuntimeWarning: Mean of empty slice
  return np.nanmean(a, axis, out=out, keepdims=keepdims)
C:\Users\gonca\AppData\Local\Programs\Python\Python311\Lib\site-packages\numpy\lib\nanfunctions.py:1215: RuntimeWarning: Mean of empty slice
  return np.nanmean(a, axis, out=out, keepdims=keepdims)

  Root cause: `Post_process._compute_metrics()` computes per-side (before/after
  collision-frame) `.mean()`/`.median()` over each disk's `vx`/`vy`/`omega_deg_s`.
  With sparse detections (this run: 46 total), a side can select a selection
  that's empty, or non-empty but entirely NaN (a disk's very first sample has
  NaN velocity/omega — it's a frame-to-frame `.diff()` with nothing before
  it) — either way pandas' `.mean()`/`.median()` still correctly returns NaN,
  but hits numpy's `nanmean` on an empty-after-dropna array to get there,
  which is where the warning actually fires. Not a wrong-result bug — the
  metric was already NaN either way and downstream code already handles NaN
  (e.g. `restitution_e` checks `np.isfinite(v_n_before)`) — just a noisy,
  confusing warning. Fixed in `Post_process.py`: added `_safe_vxvy_mean()`/
  `_safe_median()` helpers that scope-suppress specifically this
  `RuntimeWarning: Mean of empty slice` message around the calls (12 call
  sites total: 4 `vx`/`vy` means, 8 `median()`s), and used them everywhere
  `_compute_metrics()` previously called `.mean()`/`.median()` directly.
  Verified clean with `python -W error::RuntimeWarning` against the exact
  sparse CSV that reproduced it (both `build_student_excel()` and
  `visualize_trajectories()`).

- *Done* Center tracking is suficiently good but marker detection still fails around 75% of the time.

  Found two real bugs specific to smaller/dimmer markers (this video,
  `new01.mp4`, has visibly smaller/dimmer markers than `240_25.mp4`, which
  most of the color-detection tuning up to this point had been validated
  against):
  1. **`Pre_process.detect_marker_center`'s morphological "open" step used a
     fixed 7x7 kernel** — on this video's smaller marker, that erased a
     genuine 41px marker blob down to 0px (not just noise). Fixed by scaling
     the kernel to the search radius (`max(3, min(7, round(radius*0.3)|1))`).
     Also lowered `MARKER_MIN_AREA_FRAC` 0.10 -> 0.07 after the same real
     marker (once it survived the kernel fix) measured at 28.5px against a
     32.9px requirement — circularity (unchanged) is what actually carries
     the false-positive rejection burden, area is just a coarse floor.
  2. **The keypoint-anchored fallback search's "must be inside the disk"
     mask was built from the keypoint, not the disk.** It draws a circle
     around whatever point it's searching from and rejects everything
     outside it — for the primary whole-disk search that circle is centered
     on the real disk, correctly excluding background, but the fallback
     passed the *keypoint* as if it were the disk center. Since the keypoint
     is known to land off-marker ~44% of the time (bug 3 in the log above),
     an off-disk keypoint let the mask leak into background around the disk
     — measured concretely: a 414px, reasonably round (circ 0.75) false-color
     blob from background near the disk passed every existing gate this way.
     Fixed by adding `mask_center`/`mask_radius` params to
     `detect_marker_center()` so the "inside disk" circle can be pinned to
     the disk's real geometry independent of whatever point is used to
     position the search crop; `resolve_marker_color()` now passes the true
     disk center/radius for this on both the primary and keypoint-anchored
     calls. Radius needed some padding either way — measured that genuine
     marker pixels (an *offset* mark, by design near the disk's edge) can sit
     past the raw bbox radius on a small/dim marker — swept a multiplier
     against both a known true marker and this known false blob:
     1.3x-1.5x recovers the true one, 1.8x+ starts letting the false one back
     in. Landed on `MARKER_MASK_PAD_MULT = 1.4`.

  Net effect on `new01.mp4`: color coverage moved from 20/46 (43%) to 19/46
  (41%) — roughly flat in raw count, but now **correctly** green=disk0/
  blue=disk1 throughout (previously the two color's IDs were swapped for the
  whole run — see below) with zero flip-flopping, versus the false-positive
  fix from last session (`240_25.mp4`, frame 368) still holding. Also
  incidentally fixed a related bug found while investigating: because color
  was rarely detected on the very first frame both disks co-appeared, the
  deterministic left-right fallback (lowest-priority tiebreak in
  `IDAssigner`) was assigning IDs by which side of frame each disk started
  on — completely disconnected from `COLOR_ID_MAP` — and then position-lock
  (last session's fix) cemented that assignment for the whole video. More
  reliable early color detection (this session's fixes) means color-first
  assignment now correctly wins that first frame instead.

  This remains fundamentally an HSV/CV calibration problem for markers this
  small, and full elimination of both false negatives and false positives
  isn't achievable through threshold tuning alone (see CLAUDE.md bug 8,
  still true) — but the specific bugs found here (kernel erasing real
  detections; mask leaking into background) were objective, fixable defects,
  not just threshold disagreements, and are now fixed and validated against
  both known test videos.

## Working preferences

- User is Aerospace Engineering student, comfortable with Python/CV concepts, values
  direct technical explanations over hand-holding.
- Prefers to receive full code/analysis upfront and make editorial decisions independently.