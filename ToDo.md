# ToDo — pre-ship checklist


- [ ] **Notifier: log success/failure instead of swallowing silently.**
      A run on another machine finished fine but no ntfy push arrived, with
      nothing in the console to say why — `notifier.py`'s `_send()` swallows
      all exceptions and `notify_run_complete()` is a silent no-op when
      `NTFY_TOPIC` is unset. Add `[INFO]`/`[WARN]` prints (status code on
      success, exception/reason on failure, "skipped: NTFY_TOPIC unset" on
      no-op) so a future run reports what actually happened. Also double
      check that machine's `.env` has `NTFY_TOPIC` set next to the `.exe`/
      `initializer.py` and matching the phone's subscribed topic.

- [ ] **Re-run the full `New Disks` batch once the app is finalized.**
      Refresh the recall numbers currently quoted (and flagged stale) in
      CLAUDE.md's "Standing objective" once more of the 18-clip batch is
      available (10 of 18 on disk today: `3,4,5,6,7,8,10,17,18.mp4` +
      `13 - Trim.mp4`).

- [ ] **Update `Extras/README.md`** once all work is finished — currently a
      2-line stub, intentionally left untouched per your answer.



## USER Requests

You should append Done once one item here is resolved. 


- Page 3: Make ENTER button to go to the next input box. Make the Words to align left inside the box you define (whith some margin to the left end of the page). **Done**

- Page 5: Right now I see the progress bar but not the table with the logs. It shows as white, no board at all (previously when this worked I saw a grey canvas with the logs, now I don't see the canvas at all). **Done**

- Page 3: Arrows navigate through input fields (up goes up and down goes down). Enter in the last checkbox does not validate immediately. **Done** — arrow-key nav added (Up/Down move focus along the same field chain the Enter-chain already used, clamped at the first/last field). Enter-on-last-field-validates-immediately was verified already working (scripted keypress test: single Enter on the last field advances to Page 4 immediately) — couldn't reproduce a delay, so no code change was needed there; flag it again with specifics if it still shows up in real use.

- Final Page: Put the same logos as first page. Normalize them on both pages so they have the same dimentions and same resolution. **Done** — Page 6 now shows both the IST and DEM logos side by side (matching Page 1's layout), both rendered through the same `_load_logo`/`target_size` code path so sizing/resolution is identical on both pages.

- Remove the bottom bar with hints along the whole app. Remove it entorely from code. **Done** — removed `self.statusBar()`/`showMessage(...)` entirely from `app.py` and `helper.py`; the same information was already duplicated elsewhere (Page 4's upload-status label, console/genLog `[INFO]`/`[ERROR]` prints).

- Change the colors of the disks in the trajectories.png to blue and green respectively. **Done** — `Post_process.visualize_trajectories` now plots disk 0 (green) and disk 1 (blue) in their real identity colors, matching `DISK_COLOR_NAMES`.

- Is it possible the detection video that already has a circle and dot overlayed in the video now adds the lines of the paths (as the image of the trajectories and using the same colors blue and green from the previous change). Use other shade of the same colors to trace the theta position. **Done** — `detector.py` now accumulates a persistent trail overlay per disk: the center path in the disk's identity color (green/blue) and the marker/theta path in a lighter tint of that same color, composited under each frame's existing circle/dot overlay. Verified visually on a real clip. **Update (next session): the theta/marker trace was removed again per your follow-up request below** — only the center-of-mass path trace remains.

- Remove theta tracking and make the center of massed line tracker thicker. **Done** — removed the marker/theta trail line entirely (the per-frame marker dot itself, which predates the trail feature, is untouched); the remaining center-path trail line is now drawn at 4px instead of 2px.

- Make a dot where the collision occured. **Done** — `detector.py` now computes the same "recorded nearest approach" collision frame `Post_process._find_collision_frame` uses, then bakes a filled dot (disk identity color, black outline) at each disk's own position on that frame into the detection video, persisting for the rest of the clip (a second re-encode pass over the just-written video, since the collision frame isn't known until the whole clip has been processed). Verified visually on a real clip — dot appears at the trail's bend point and stays visible afterward.

- Logos both at the first and last pages are not the same size (you may need to normalize the logos by editing them). **Done** — root cause was the source PNGs themselves: `Images/logoDEM.png`'s actual logo content only filled ~41% of its canvas height vs. `Images/logoIST.png`'s ~63%, so scaling both into the same bounding box (already identical between pages, see the "Final Page" logo item above) still left the DEM mark looking smaller. Cropped both `Images/logoIST.png` and `Images/logoDEM.png` to their content bounding box plus a uniform 5% padding margin, so both now fill ~91% of their own canvas — verified via an offscreen render that the two shield marks now read as the same size.