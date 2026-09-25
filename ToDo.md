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

- App opens full screen but still windowed. 

- First Page: Imagens closer to each other and bigger. 

- Second Page: Bullets points are not aligned with the phrases. Words need to be bigger, you have a full screen so there is margin. 

- Third Page: Overall good, just increase all the sizes so that fills the page. 

- Progress bar should not have border. Remove also the percentage and done indications. INFO and WARNS still don't show below. I am running through initializer.py so that does not depend on build. 