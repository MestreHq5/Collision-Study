# ToDo — pre-ship checklist

Reviewed on 2026-09-23, on `main` right after merging `color-thresholding`
(fast-forward, verified with a before/after run on `New Disks\7.mp4` —
identical detections, e, momentum error, energy drop). Below is everything
found still open or unfinished. Add priorities / strike out as you go.

**2026-09-23 update**: all answered items below were acted on in branch
`gr/tweaks`, in small chunks (see its commit log for exact diffs). A few
items are intentionally left open — they're your own follow-up action, not
something code could resolve, and are marked as such.

## Data quality (open, not root-caused — see CLAUDE.md "Standing objective")

- [x] Raw disk *position* recall across a clip's full duration is often only
      ~10-40% on the `New Disks` batch. Not necessarily alarming (most of a
      clip is before/after the active throw window) but caps how much data
      exists for theta fitting regardless of marker quality. Revisit once
      more of the originally-referenced 18-clip batch is available (only
      10 are on disk today: `3,4,5,6,7,8,10,17,18.mp4` + `13 - Trim.mp4`).

Answer: this information seems stale.
→ Done (gr/tweaks): CLAUDE.md "Standing objective" now flags the 10-40%
  figure as stale and not to be cited as current; re-measurement is
  explicitly deferred until the app is finalized (your call, not a
  code change).

- [x] Sparse both-disk coverage specifically *around the collision moment*
      on some clips → noisy velocity fit → less reliable e/momentum on those
      clips. Traced to real fast motion between frames (not an ID/tracking
      bug), but root cause of the density drop itself (motion blur at
      contact? shape gates too strict under partial occlusion?) is still
      open.

Answer: for now it is working but later studies will use 120 or 240 fps to unlock this issue.
→ Done (gr/tweaks): decision recorded in CLAUDE.md as an accepted 60fps
  limitation, with the 120/240fps study-phase plan noted as the actual
  fix, not further gate-tuning.

- [x] `estimate_background_median`'s puck mask only excludes pixels a puck
      was *detected* covering during the sample window — a puck sitting
      somewhere undetected for the whole window still isn't protected.
      Edge case, not hit yet.

Answer: not a problem because disks only enter the windows after 2-3 seconds.
→ Done (gr/tweaks): moved to CLAUDE.md's Resolved list as a non-issue,
  with your reasoning recorded.

- [x] `collision_gap_mm` threshold/policy: at 56-60fps some "collisions"
      may just be undersampled near-misses, not real contact. The
      diagnostic exists (`Post_process._compute_metrics`) but nothing yet
      distinguishes "real but undersampled" from "no collision happened."
      Needs a threshold once more data exists on what each case typically
      looks like.

Answer: if the gap at collision frame is undersampled, let's say at more than a radius distance, them just trigger a warning.
→ Done (gr/tweaks): `_compute_metrics` now prints `[WARN]` and sets
  `collision_gap_warning=True` (also a Results-sheet row) when
  `collision_gap_mm` exceeds one disk radius.

- [x] `Other_Side`-style clips (cramped side, disk bounces off the boundary
      and comes back) still require manual trimming before running through
      the pipeline — there's no automated check/warning if someone feeds in
      an untrimmed multi-bounce clip.

Answer: as per previous tests, other_side tests are no longer an option. they were outperforming.
→ Done (gr/tweaks): filming location discontinued — CLAUDE.md's Lab/
  lighting history and Known bugs both updated; the manual-trim item is
  moot, not just unaddressed.

## Notifier (`notifier.py` — uncommitted, in progress)

- [ ] Decide scope/requirements properly (CLAUDE.md's long-term-issues list
      flagged this as "not designed yet, don't start until asked" — it's
      since been built ahead of that, uncommitted). Needs: push vs. pull,
      who else needs access, hosting expectations.

    Answer: Notifier app was tested but not live tested. I will do it now.
→ Left open — your own live test, not a code task. CLAUDE.md's new
  "Notifier" section documents the scope as actually built.

- [x] Currently a synchronous `requests.post` call at the end of
      `build_student_excel` — on the GUI's `genData()` path this blocks the
      GUI thread on a network call (ntfy.sh). Should probably move off the
      main thread or get a short/no-network-hang timeout guarantee.

Answrr: yes, please correct this
→ Done (gr/tweaks): `notify_run_complete` now fires on a daemon
  background thread.

- [x] No way to opt out per-run from the GUI — only via unsetting the
      `NTFY_TOPIC` env var machine-wide. Consider a GUI toggle if this is
      going to be used across multiple student groups/machines.

Answer: this is mandatory for me to receice. I receive the information and this validates if the test was sucessfull or not. If not they will repeat.
→ Done (gr/tweaks): left as machine-wide-only by design; CLAUDE.md's
  Notifier section documents this as intentional, not a gap.

- [x] Either commit it (and add `requests` to a real dependency manifest —
      see below) or park it on its own branch — right now it's uncommitted
      on `main`.

Answer: temporarily commited. I will open other branches for this feature checks.
→ No action needed — already committed on `main` per your own note;
  `requests` (and `python-dotenv`) are now in `requirements.txt`.

## Testing / validation

- [x] No automated tests anywhere in the repo (`results_regression.py` was
      removed in the `color-thresholding` cleanup and nothing replaced it).
      All verification so far (including this session's merge check) has
      been manual, ad hoc scripts. Worth at least a small regression
      harness: run the pipeline on 1-2 known clips and assert
      e/momentum/energy/collision_gap stay within tolerance, so a future
      change can be checked in seconds instead of a manual before/after run.

      Answer: Ignore this pipeline. It is not worth to build the tests.
→ No action taken, per your answer.

- [ ] Once more of the `New Disks` batch (18 clips referenced, 10 present)
      is available, re-run the full batch end to end and refresh the
      recall numbers currently quoted in CLAUDE.md.

      Answer: once I finalize the app we can check this.
→ Left open — deferred to when the app is finalized, per your answer.

## Repo hygiene

- [x] No `.gitignore` — compiled `__pycache__/*.pyc` files are tracked in
      git, including for source files that no longer exist at all
      (`webcam.py`, `resources_rc.py` — from the old live-camera-recording
      feature). Add a `.gitignore` (at least `__pycache__/`, `*.pyc`) and
      remove the stale tracked ones.

    Answer: Already in the todo list below
→ Done (gr/tweaks): `.gitignore` added, all 8 tracked `.pyc` files
  untracked (including the 2 for already-deleted `webcam.py`/
  `resources_rc.py`).

- [x] No dependency manifest (`requirements.txt` / `pyproject.toml`).
      Current runtime deps observed: `opencv-python`, `pandas`, `openpyxl`,
      `matplotlib`, `PyQt6`, and (if the notifier ships) `requests`.

Answer: Not sure what you mean by this, do you want to explain?
→ Done (gr/tweaks): added `requirements.txt`. A dependency manifest is
  just a plain-text list of the packages the app needs (`pip install -r
  requirements.txt` reproduces the environment on a new machine or CI
  runner) — otherwise you're relying on whatever happens to already be
  installed, which silently breaks a fresh checkout/machine.

- [x] `CollisionStudy.spec` (PyInstaller build spec) was deleted as part of
      the YOLO-removal cleanup. No packaging path exists right now for a
      distributable build — needs a fresh spec (see `Notes.txt` for the
      last known-working `pyinstaller` invocation, minus anything YOLO/model
      related it no longer needs: no more `.pt` weights, no
      `Puck_Training*`/`runs*` data to bundle).

Answer: Update this.
→ Done (gr/tweaks): fresh `CollisionStudy.spec` added, rebuilt from the
  invocation recorded in `Notes.txt` (since removed), no YOLO leftovers.

- [x] `GEMINI.md` is stale — documents a "Live Record" camera flow
      (`CameraWorker`, `QThread`-based recording, the `mpeg4`/OpenCV
      `VideoWriter` "Invalid pts" bug) that no longer exists in `app.py`.
      Current app is upload-only (`select_video_file`). Update or delete.

Answer: remove it completely.
→ Done (gr/tweaks): removed.

- [x] `Extras/README.md` is a 2-line stub; `Extras/Prompt.txt` and
      `Notes.txt` are personal scratch notes mixed into the repo root/
      Extras — worth deciding what's kept as real docs vs. cleared out.

Answer: Notes can be remove. README can be updated but only when all the work is finished.
→ Partially done (gr/tweaks): `Notes.txt` and `Extras/Prompt.txt`
  removed. `Extras/README.md` intentionally left untouched — update it
  once you say all the work is finished.

- [x] `main` is currently 16 commits ahead of `origin/main` (this session's
      merge hasn't been pushed) — push when ready.

      Answer: I already changed this. Nothing more to do.
→ No action needed.

## Physical / hardware (from CLAUDE.md — carry over, no code fix possible)

- [x] Confirm the repaint to a brighter/lighter green is actually
      happening — `MARKER_DARK_VALUE_FRAC_GREEN` is a documented software
      workaround for the current dark green paint, not the real fix.
      Once repainted, re-sweep and consider merging the green/blue dark-
      value constants back into one.

    Answer: the final green color is the current one. The color threshold was changed and the app is working so I don't think a repaint is still necessary.
→ Done (gr/tweaks): CLAUDE.md updated — `MARKER_DARK_VALUE_FRAC_GREEN`
  is now documented as the permanent fix, not a stopgap.

- [x] Any remaining clips from the earlier grey-dimple disk batch (`17`,
      `18.mp4`) should be treated as known-lower-contrast, not representative
      of current black-dimple disks, when judging recall numbers.

    Answer: Grey dimple disks will no longer be used.
→ Done (gr/tweaks): already framed as historical/closed in CLAUDE.md;
  no code depends on grey-dimple handling.

## USER LIST

1. The data that prints on the screen using square brackets could actually print alongside the loading screen on the GUI. Don't acept all the prints, only the ones manually added. Some from Qpainter on windows switch etc should be discarded for this effect.
→ Done (gr/tweaks): `helper.PrintTee` mirrors `[INFO]`/`[WARN]`/`[ERROR]`-
   tagged prints into a new `genLog` box on Page 5; untagged noise
   (matplotlib/Qt/cv2, ad hoc debug prints) stays console-only. Verified
   headless.

2. Even if you use internally disk0 and disk1, the excel should showthe true color like Green or Blue disks because it is easier for the students to recall them.
→ Done (gr/tweaks): Raw_Data's `disk_id` column now shows "Green"/"Blue".

3. The notifier should try to upload to me the metrics only, that means the second sheet of the excel along with the percentage of interpolation to measured data (this could be a new row on the second sheet). The second sheet should no longer be printed (I think there is a flag on the code but make it some env variable that I can switch when I need)
→ Done (gr/tweaks): notifier sends metrics text only (no more xlsx
   attachment); added a "Theta interpolation %" row; the Results sheet's
   presence in the delivered `.xlsx` is now gated by `DEM_SHOW_RESULTS_SHEET`
   (env var, see `.env.example`), default off.

4. Build a .env to remove the garbage data that is generated each run.
→ Done (gr/tweaks), per your clarification ("move hardcoded paths into
   .env, no auto-delete, + gitignore pycache"): `DEM_WORKSPACE_ROOT` and
   `NTFY_TOPIC` moved to `.env`/`.env.example`; `__pycache__` gitignored.

5. Build a pipeline to build excutable app with left windows beeing the app itself and the right one the terminal
→ Done (gr/tweaks), as I understood it: `CollisionStudy.spec` (item
   above) builds a `--console` executable, and the app now auto-positions
   the console window into the right half of the screen on launch
   (`app._position_console_right`), alongside its own existing left-half
   placement. Flag if you meant something different here.
