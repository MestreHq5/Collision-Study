# ToDo — pre-ship checklist

New branch for wiring a Live Feed Camera onto the app. 

The objective is switch page 4 that now selects the video to have both options: two buttons, one to select the video and other to record the video. If the user selects the video pre-recorded them the pipeline is the one implemented with the buttons to choose and proceed popping up now. 

If the user selects the LiveFeed then it changes to another page using this conditional statement. 

Once both pipelines, either pre-recorded or liveFeed have a real video, then proceed to the same page for the generation and preview. 


For the liveFeed camera, add a Title "Live Feed", buttons to Record, Stop, Repeat, Next. Buttons are disabled or enable logically in their own times. 

Add a small area with the definitions of the camera (select camera if more than one), select resolutions and frame rate, etc.

For the camera related funcions create a new file called cameraFeed.py

**Status (2026-09-26): Done on the laptop webcam -- pending a test on the external USB lab
camera.** "No camera found" bug fixed (an empty QComboBox is falsy in PyQt6, so the camera list
was never probed). Also fixed: MJPG negotiation (needed for 1080p60), writer size from the actual
frames, container fps = measured fps (the detector trusts it), writer on its own thread, live
"WxH @ fps" readout with warnings. Verified end to end in the real app with the laptop webcam
(720p30). Remaining: plug in the lab camera and confirm the readout shows 1920x1080 @ ~60 fps.
See CLAUDE.md "Page Live Feed".
