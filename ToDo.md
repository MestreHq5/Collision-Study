# ToDo — pre-ship checklist

New branch for wiring a Live Feed Camera onto the app. 

The objective is switch page 4 that now selects the video to have both options: two buttons, one to select the video and other to record the video. If the user selects the video pre-recorded them the pipeline is the one implemented with the buttons to choose and proceed popping up now. 

If the user selects the LiveFeed then it changes to another page using this conditional statement. 

Once both pipelines, either pre-recorded or liveFeed have a real video, then proceed to the same page for the generation and preview. 


For the liveFeed camera, add a Title "Live Feed", buttons to Record, Stop, Repeat, Next. Buttons are disabled or enable logically in their own times. 

Add a small area with the definitions of the camera (select camera if more than one), select resolutions and frame rate, etc.

For the camera related funcions create a new file called cameraFeed.py

**Status (2026-09-25): Implemented, but blocked on a real-machine camera bug — paused, picking
back up another day.** Page 4 has Select Video File / Record Video buttons; a new "Live Feed"
page (Title, camera/resolution/fps dropdowns, live preview, Record/Stop/Repeat/Next, a Play/
Stop overlay button on the video for reviewing a take) sits between Upload and Analysis/
Generate. `cameraFeed.py` holds all capture/recording/playback logic.

**Open, not yet root-caused**: first the webcam only delivered ~1 frame/second through OpenCV
(likely this machine's lighting/auto-exposure, not this code). After closing other apps and a
retry, the app now reports "no camera found" even though a plain script opened the same device
fine moments later outside the app — not explained yet. See CLAUDE.md's "Page Live Feed"
subsection (under "GUI / UX") for the full diagnostic and the next debugging steps to try.