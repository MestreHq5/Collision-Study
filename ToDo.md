# ToDo — pre-ship checklist

Reviewed on 2026-09-23, on `main` right after merging `color-thresholding`
(fast-forward, verified with a before/after run on `New Disks\7.mp4` —
identical detections, e, momentum error, energy drop). Below is everything
found still open or unfinished. Add priorities / strike out as you go.

## Data quality (open, not root-caused — see CLAUDE.md "Standing objective")

- [ ] Raw disk *position* recall across a clip's full duration is often only
      ~10-40% on the `New Disks` batch. Not necessarily alarming (most of a
      clip is before/after the active throw window) but caps how much data
      exists for theta fitting regardless of marker quality. Revisit once
      more of the originally-referenced 18-clip batch is available (only
      10 are on disk today: `3,4,5,6,7,8,10,17,18.mp4` + `13 - Trim.mp4`).
- [ ] Sparse both-disk coverage specifically *around the collision moment*
      on some clips → noisy velocity fit → less reliable e/momentum on those
      clips. Traced to real fast motion between frames (not an ID/tracking
      bug), but root cause of the density drop itself (motion blur at
      contact? shape gates too strict under partial occlusion?) is still
      open.
- [ ] `estimate_background_median`'s puck mask only excludes pixels a puck
      was *detected* covering during the sample window — a puck sitting
      somewhere undetected for the whole window still isn't protected.
      Edge case, not hit yet.
- [ ] `collision_gap_mm` threshold/policy: at 56-60fps some "collisions"
      may just be undersampled near-misses, not real contact. The
      diagnostic exists (`Post_process._compute_metrics`) but nothing yet
      distinguishes "real but undersampled" from "no collision happened."
      Needs a threshold once more data exists on what each case typically
      looks like.
- [ ] `Other_Side`-style clips (cramped side, disk bounces off the boundary
      and comes back) still require manual trimming before running through
      the pipeline — there's no automated check/warning if someone feeds in
      an untrimmed multi-bounce clip.

## Notifier (`notifier.py` — uncommitted, in progress)

- [ ] Decide scope/requirements properly (CLAUDE.md's long-term-issues list
      flagged this as "not designed yet, don't start until asked" — it's
      since been built ahead of that, uncommitted). Needs: push vs. pull,
      who else needs access, hosting expectations.
- [ ] Currently a synchronous `requests.post` call at the end of
      `build_student_excel` — on the GUI's `genData()` path this blocks the
      GUI thread on a network call (ntfy.sh). Should probably move off the
      main thread or get a short/no-network-hang timeout guarantee.
- [ ] No way to opt out per-run from the GUI — only via unsetting the
      `NTFY_TOPIC` env var machine-wide. Consider a GUI toggle if this is
      going to be used across multiple student groups/machines.
- [ ] Either commit it (and add `requests` to a real dependency manifest —
      see below) or park it on its own branch — right now it's uncommitted
      on `main`.

## Testing / validation

- [ ] No automated tests anywhere in the repo (`results_regression.py` was
      removed in the `color-thresholding` cleanup and nothing replaced it).
      All verification so far (including this session's merge check) has
      been manual, ad hoc scripts. Worth at least a small regression
      harness: run the pipeline on 1-2 known clips and assert
      e/momentum/energy/collision_gap stay within tolerance, so a future
      change can be checked in seconds instead of a manual before/after run.
- [ ] Once more of the `New Disks` batch (18 clips referenced, 10 present)
      is available, re-run the full batch end to end and refresh the
      recall numbers currently quoted in CLAUDE.md.

## Repo hygiene

- [ ] No `.gitignore` — compiled `__pycache__/*.pyc` files are tracked in
      git, including for source files that no longer exist at all
      (`webcam.py`, `resources_rc.py` — from the old live-camera-recording
      feature). Add a `.gitignore` (at least `__pycache__/`, `*.pyc`) and
      remove the stale tracked ones.
- [ ] No dependency manifest (`requirements.txt` / `pyproject.toml`).
      Current runtime deps observed: `opencv-python`, `pandas`, `openpyxl`,
      `matplotlib`, `PyQt6`, and (if the notifier ships) `requests`.
- [ ] `CollisionStudy.spec` (PyInstaller build spec) was deleted as part of
      the YOLO-removal cleanup. No packaging path exists right now for a
      distributable build — needs a fresh spec (see `Notes.txt` for the
      last known-working `pyinstaller` invocation, minus anything YOLO/model
      related it no longer needs: no more `.pt` weights, no
      `Puck_Training*`/`runs*` data to bundle).
- [ ] `GEMINI.md` is stale — documents a "Live Record" camera flow
      (`CameraWorker`, `QThread`-based recording, the `mpeg4`/OpenCV
      `VideoWriter` "Invalid pts" bug) that no longer exists in `app.py`.
      Current app is upload-only (`select_video_file`). Update or delete.
- [ ] `Extras/README.md` is a 2-line stub; `Extras/Prompt.txt` and
      `Notes.txt` are personal scratch notes mixed into the repo root/
      Extras — worth deciding what's kept as real docs vs. cleared out.
- [ ] `main` is currently 16 commits ahead of `origin/main` (this session's
      merge hasn't been pushed) — push when ready.

## Physical / hardware (from CLAUDE.md — carry over, no code fix possible)

- [ ] Confirm the repaint to a brighter/lighter green is actually
      happening — `MARKER_DARK_VALUE_FRAC_GREEN` is a documented software
      workaround for the current dark green paint, not the real fix.
      Once repainted, re-sweep and consider merging the green/blue dark-
      value constants back into one.
- [ ] Any remaining clips from the earlier grey-dimple disk batch (`17`,
      `18.mp4`) should be treated as known-lower-contrast, not representative
      of current black-dimple disks, when judging recall numbers.
