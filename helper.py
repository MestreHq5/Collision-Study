from pathlib import Path
import re
import sys
import os
import shutil
import cv2
import detector as dtc
import Post_process as ptp
import cameraFeed as camf
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QObject, QSize, QThread, pyqtSignal
from PyQt6.QtWidgets import QFileDialog

_BRACKET_TAG_RE = re.compile(r"^\[[A-Za-z]+\]")


class PrintTee(QObject):
    """
    Tees stdout so the [INFO]/[WARN]/[ERROR]-tagged prints this codebase adds
    deliberately (app.py, helper.py, detector.py's info()) also reach the
    GUI's genLog box on Page 5, without losing the original console output.
    Everything else (matplotlib/Qt/cv2 noise, ad hoc debug prints in
    Pre_process.py) has no bracket tag and stays console-only -- see the
    USER LIST request this answers: "only the ones manually added."

    Buffers by line since print() issues separate write() calls for the
    message and the trailing newline. A QObject (not a plain wrapper) so
    line_ready can be emitted safely from detector.main()'s background
    QThread (DetectionWorker) and queued onto the GUI thread by Qt, the same
    pattern DetectionWorker.progress already uses.
    """
    line_ready = pyqtSignal(str)

    def __init__(self, real_stream):
        super().__init__()
        self._real = real_stream
        self._buf = ""

    def write(self, text):
        self._real.write(text)
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if _BRACKET_TAG_RE.match(line):
                self.line_ready.emit(line)

    def flush(self):
        self._real.flush()

    def isatty(self):
        return False


def resource_path(*parts) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base.joinpath(*parts)


def file_manager(parent_folder: str, child_folder: str) -> Path:
    # DEM_WORKSPACE_ROOT (see .env.example) overrides the default
    # Desktop/<parent_folder> location -- unset behaves exactly as before.
    root = os.environ.get("DEM_WORKSPACE_ROOT")
    desktop = Path(root) if root else Path(os.path.expanduser("~")) / "Desktop"
    base = desktop / parent_folder
    base.mkdir(parents=True, exist_ok=True)
    sub = base / str(child_folder)
    sub.mkdir(parents=True, exist_ok=True)
    return sub


def validate_input(group, massB, massG, radiusB, radiusG):
    message = ""
    if group is not None and group != "":
        group = str(group)
    else:
        return "INVALID GROUP"

    try:
        float(massB)
    except ValueError:
        return "INVALID BLUE DISK MASS"

    try:
        float(massG)
    except ValueError:
        return "INVALID GREEN DISK MASS"

    try:
        float(radiusB)
    except ValueError:
        return "INVALID BLUE DISK RADIUS"

    try:
        float(radiusG)
    except ValueError:
        return "INVALID GREEN DISK RADIUS"

    return message


def eraser(self):
    self.group_val.setText("")
    self.green_mass_val.setText("")
    self.blue_mass_val.setText("")
    self.green_rad_val.setText("")
    self.blue_rad_val.setText("")


def validator(self):
    group_val = self.group_val.text()
    green_mass_val = self.green_mass_val.text()
    blue_mass_val = self.blue_mass_val.text()
    green_rad_val = self.green_rad_val.text()
    blue_rad_val = self.blue_rad_val.text()

    message = validate_input(group_val, blue_mass_val, green_mass_val, blue_rad_val, green_rad_val)

    if message == "":
        # Set up the run workspace directory 
        self.path = file_manager("Collision_Study", group_val)
        
        # Clear any old warning message
        self.warning_Label.setText("")
        
        # Go cleanly to Page 4 (Upload Page) instead of popping up files instantly
        self.stack.setCurrentIndex(3)
    else:
        self.warning_Label.setText(message)
        print(f"[WARN]: {message}")
        eraser(self)


class DetectionWorker(QThread):
    """
    Runs detector.main() off the GUI thread so the window stays responsive
    and can show real progress instead of freezing for the whole run (that
    call processes the video frame-by-frame, easily tens of seconds to
    minutes). progress reports (frame_idx, total_frames);
    only emitted when the integer percentage actually changes, so a
    thousands-of-frames run doesn't queue thousands of cross-thread signal
    emissions for no visible benefit. QThread's built-in `finished` signal
    covers completion (success or failure); `error` carries a message for
    the failure case specifically.
    """
    progress = pyqtSignal(int, int)
    error = pyqtSignal(str)

    def __init__(self, video_path, bg_path, detection_video_path, csv_path, fps_eff):
        super().__init__()
        self.video_path = video_path
        self.bg_path = bg_path
        self.detection_video_path = detection_video_path
        self.csv_path = csv_path
        self.fps_eff = fps_eff
        self._last_pct = -1
        self.succeeded = False  # checked by _generation_finished, since QThread's
        # `finished` signal fires whether run() succeeded or hit the except below

    def _on_progress(self, frame_idx, total_frames):
        pct = int(frame_idx * 100 / total_frames) if total_frames > 0 else 0
        if pct != self._last_pct:
            self._last_pct = pct
            self.progress.emit(frame_idx, total_frames)

    def run(self):
        try:
            dtc.main(self.video_path, self.bg_path, self.detection_video_path, self.csv_path,
                      self.fps_eff, progress_callback=self._on_progress)
            self.succeeded = True
        except Exception as e:
            self.error.emit(str(e))


def generate(self):
    video_path = self.video_path
    parent_path = self.parent_path
    bg_path = parent_path / "table_background.png"
    detection_video_path = parent_path / "detection.mp4"
    csv_path = parent_path / "disk_tracks.csv"

    self.progressGen.setVisible(True)
    self.progressGen.setRange(0, 100)
    self.progressGen.setValue(0)

    if self.genLog:
        self.genLog.clear()
        self.genLog.setVisible(True)

    # Kept on self so the QThread object isn't garbage-collected mid-run.
    self._detectionWorker = DetectionWorker(video_path, bg_path, detection_video_path, csv_path, self.fps_eff)
    # Connected to real bound methods on `self` (MainWindow, a QObject that
    # lives on the GUI thread) rather than a bare lambda/function -- PyQt
    # can only auto-detect a signal/slot connection's thread affinity, and
    # therefore correctly queue it back onto the GUI thread, when the slot
    # is a QObject's own bound method. A plain lambda has no owning QObject
    # for Qt to key off, so it would run directly on the worker thread
    # instead -- unsafe for anything that touches a widget.
    self._detectionWorker.progress.connect(self._on_gen_progress)
    self._detectionWorker.error.connect(self._on_gen_failed)
    self._detectionWorker.finished.connect(self._on_gen_finished)
    self._detectionWorker.start()


def _update_progress(self, frame_idx, total_frames):
    pct = int(frame_idx * 100 / total_frames) if total_frames > 0 else 0
    self.progressGen.setValue(min(pct, 100))


def _generation_finished(self):
    # QThread's finished signal fires whether run() succeeded or hit the
    # except -- only advance the UI to "done" on the success path;
    # _generation_failed already handled the UI for the other one.
    if self._detectionWorker.succeeded:
        self.progressGen.setValue(100)
        self.btnPreview.setEnabled(True)
        # Build the Excel + fire notify_run_complete (see genData/
        # build_student_excel) right here, as soon as results exist and
        # Preview becomes clickable -- not gated behind the user actually
        # clicking Preview. The Excel/metrics only need the CSV detection
        # just wrote, not the trajectory plot preview() renders, so the two
        # are independent and this doesn't need to wait for a click.
        genData(self)


def _generation_failed(self, message):
    self.btnGen.setEnabled(True)
    print(f"[ERROR] Detection failed: {message}")


def _trajectory_figsize_for_label(self):
    """
    Figure (width, height) in inches matching detectionLabel's current
    aspect ratio, at the same total area as visualize_trajectories' 12x8
    default (96 sq. in.) so overall detail/DPI-per-area stays comparable --
    only the width:height split changes. Returns None if the label has no
    usable size yet.

    Why this matters: Qt's KeepAspectRatio scaling (used to display the
    saved plot in detectionLabel) letterboxes -- blank bars, not lower pixel
    density -- whenever the source image's aspect ratio doesn't match the
    label's. This app's default window is now full-height/half-width (tall,
    narrow), a bad mismatch against a fixed 12x8 *landscape* plot, and that
    letterboxing is what actually made the displayed plot look small/
    "low-resolution" -- the saved PNG's own pixel density was never the
    problem (measured: 3600x2400 @ 300dpi, axes already filling nearly the
    whole canvas). Matching the figure's shape to the label's directly fixes
    the display size instead of just pushing more unneeded pixels into an
    unchanged small letterboxed area.
    """
    label_w, label_h = self.detectionLabel.width(), self.detectionLabel.height()
    if label_w <= 0 or label_h <= 0:
        return None
    area = 12.0 * 8.0
    aspect = label_w / label_h
    fig_h = (area / aspect) ** 0.5
    fig_w = area / fig_h
    return (fig_w, fig_h)


def preview(self):
    csv_path = self.parent_path / "disk_tracks.csv"
    output_path = self.parent_path / "trajectories.png"
    figsize = _trajectory_figsize_for_label(self) or (12, 8)
    ptp.visualize_trajectories(csv_path, output_path, self.fps_eff, show_equal_aspect=True, figsize=figsize)

    self.detectionLabel.setScaledContents(False)
    # Keep the full-resolution (300 dpi, see Post_process.py) render around so
    # apply_trajectory_pixmap can display straight from this source. Also
    # keep the CSV path around implicitly via self.parent_path so a later
    # window resize (MainWindow.resizeEvent -> apply_trajectory_pixmap) can
    # regenerate the plot at the new aspect ratio, not just rescale this one.
    self._trajectory_pixmap_orig = QPixmap(str(output_path))
    apply_trajectory_pixmap(self)


def apply_trajectory_pixmap(self):
    """
    Refreshes detectionLabel's trajectory plot for its current size. Called
    once right after generating the plot (preview()) and again (debounced)
    on every window resize (MainWindow.resizeEvent) so the plot keeps
    filling the available space as the user resizes instead of sitting at
    its first-render shape/size. No-op if nothing's been generated yet.

    Prefers regenerating the actual matplotlib figure at the new aspect
    ratio (via _trajectory_figsize_for_label) over merely rescaling the
    existing bitmap -- a resize that changes the label's aspect ratio would
    otherwise reintroduce the same letterboxing preview() avoids at first
    render (see _trajectory_figsize_for_label's docstring). Only falls back
    to a plain rescale of the stored bitmap if the source CSV isn't
    available any more for some reason (e.g. the workspace was cleared) --
    still device-pixel-ratio aware either way so the result stays sharp on
    HiDPI displays instead of Qt stretching a logical-pixel-sized image up
    to the physical pixel grid.
    """
    if getattr(self, "_trajectory_pixmap_orig", None) is None:
        return

    parent_path = getattr(self, "parent_path", None)
    csv_path = parent_path / "disk_tracks.csv" if parent_path is not None else None
    figsize = _trajectory_figsize_for_label(self)
    if csv_path is not None and csv_path.exists() and figsize is not None:
        output_path = parent_path / "trajectories.png"
        ptp.visualize_trajectories(csv_path, output_path, self.fps_eff,
                                    show_equal_aspect=True, figsize=figsize)
        self._trajectory_pixmap_orig = QPixmap(str(output_path))

    pixmap = self._trajectory_pixmap_orig
    if pixmap is None or pixmap.isNull():
        return
    dpr = self.devicePixelRatioF()
    target = self.detectionLabel.size()
    if target.width() <= 0 or target.height() <= 0:
        return
    device_size = QSize(max(1, int(target.width() * dpr)), max(1, int(target.height() * dpr)))
    scaled = pixmap.scaled(device_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    scaled.setDevicePixelRatio(dpr)
    self.detectionLabel.setPixmap(scaled)


def genData(self):
    csv_path = self.parent_path / "disk_tracks.csv"
    output_path = self.parent_path / "data.xlsx"
    fps = self.fps_eff
    
    green_mass_val = float(self.green_mass_val.text())
    blue_mass_val = float(self.blue_mass_val.text())
    green_rad_val = float(self.green_rad_val.text())
    blue_rad_val = float(self.blue_rad_val.text())
    
    masses = (green_mass_val, blue_mass_val)
    radius = (green_rad_val, blue_rad_val)

    ptp.build_student_excel(csv_path, output_path, masses, radius, fps, include_metrics=True,
                             group_name=self.parent_path.name)

    self.btnRedo.setEnabled(True)
    self.btnNext5.setEnabled(True)
    

def analisysPage(self):
    self.btnGen.setEnabled(True)
    self.btnPreview.setEnabled(False)
    self.btnRedo.setEnabled(False)
    self.btnNext5.setEnabled(False)

    self.progressGen.setVisible(False)
    self.progressGen.setValue(0)

    if self.genLog:
        self.genLog.clear()
        self.genLog.setVisible(False)

    self.detectionLabel.clear()
    self._trajectory_pixmap_orig = None
    # Navigation to Page 5 is the caller's job (app.py's btnProceed/
    # btnNextLive handlers both set the stack index alongside calling this) --
    # this function only resets Page 5's own widget state for a fresh run.
    # A prior version set the stack index here too, redundantly and to a
    # stale literal (both callers used to double-connect around it -- see
    # app.py's btnProceed wiring comment).

    
def redo(self):
    # Sends user straight back to data input form to upload a new video file
    self.stack.setCurrentIndex(2)


# ---------------------------------------------------------------------------
# Page "Live Feed" -- camera preview, recording and playback. All actual
# capture/write logic lives in cameraFeed.py (CameraWorker/PlaybackWorker);
# this section only owns page state and widget wiring, same split as
# generate()/DetectionWorker above.
# ---------------------------------------------------------------------------

def _live_feed_status_html(text):
    return (f'<html><body><p align="center"><span style="font-size:14pt; color:#555555;">'
            f'{text}</span></p></body></html>')


def _refresh_camera_list(self):
    """
    Re-probes for cameras and rebuilds cameraCombo from scratch -- unlike
    resolution/fps (fixed presets, never need re-reading), which camera(s)
    are actually openable can change between one moment and the next (another
    app releasing/taking the device, a USB webcam being plugged in), so this
    is NOT guarded to run once -- called on every liveFeedPageEnter, and again
    from startRecording as a retry when no camera was available at page-enter
    time. Signals blocked during the rebuild so the clear()+repopulate cycle
    doesn't fire on_live_feed_settings_changed for every intermediate state.
    """
    if not self.cameraCombo:
        return
    self.cameraCombo.blockSignals(True)
    self.cameraCombo.clear()
    cameras = camf.list_cameras()
    self._camera_devices = cameras
    for idx, name in cameras:
        self.cameraCombo.addItem(name, idx)
    if not cameras:
        self.cameraCombo.addItem("No camera found", -1)
    self.cameraCombo.blockSignals(False)


def _populate_live_feed_combos(self):
    """
    Resolution/fps are idempotent (guarded by each combo's own count()) so
    calling this again on a later page re-entry doesn't duplicate entries or
    reset the student's already-chosen resolution/fps. The camera list is not
    -- see _refresh_camera_list. Order matters: resolution and fps are filled
    before the camera list so that once the camera combo gets its first item
    (firing currentIndexChanged -> on_live_feed_settings_changed),
    resolutionCombo/fpsCombo already have valid currentData to read.
    """
    if self.resolutionCombo and self.resolutionCombo.count() == 0:
        for w, h in camf.RESOLUTION_PRESETS:
            self.resolutionCombo.addItem(f"{w}x{h}", (w, h))
    if self.fpsCombo and self.fpsCombo.count() == 0:
        for fps in camf.FPS_PRESETS:
            self.fpsCombo.addItem(f"{fps} fps", fps)
    _refresh_camera_list(self)


def _stop_camera_worker(self):
    worker = getattr(self, "_cameraWorker", None)
    if worker is not None:
        worker.stop()
    self._cameraWorker = None


def _stop_playback_worker(self):
    worker = getattr(self, "_playbackWorker", None)
    if worker is not None:
        worker.stop()
    self._playbackWorker = None


def _start_camera_preview(self):
    """(Re)starts the live camera loop with whatever the settings row currently
    has selected. Safe to call while a previous worker is running -- stops it
    (synchronously, so the device is actually released) first."""
    _stop_camera_worker(self)

    device_index = self.cameraCombo.currentData() if self.cameraCombo else None
    resolution = self.resolutionCombo.currentData() if self.resolutionCombo else None
    fps = self.fpsCombo.currentData() if self.fpsCombo else None
    # device_index can legitimately be 0 (the first camera) -- checking
    # `is None`, not truthiness, matters here.
    if device_index is None or device_index < 0 or resolution is None or fps is None:
        # DirectShow only lets one process hold a UVC camera at a time -- the
        # likeliest real-world cause is another app (Teams/Zoom/the Windows
        # Camera app/a leftover script) already having it open. Printed (not
        # just shown in the status label) so it reaches genLog/console like
        # every other [WARN] in this codebase, instead of failing silently.
        print("[WARN] Live Feed: no camera could be opened -- check whether "
              "another application currently has the camera in use.")
        if self.lblLiveFeedStatus:
            self.lblLiveFeedStatus.setText(_live_feed_status_html(
                "No camera available. Close any other app using the camera and retry."
            ))
        return

    width, height = resolution
    dest_path = self.path / "Recording.mp4"
    worker = camf.CameraWorker(device_index, width, height, fps, dest_path)
    worker.frame_ready.connect(self._on_camera_frame)
    worker.error.connect(self._on_camera_error)
    worker.recording_finished.connect(self._on_recording_finished)
    self._cameraWorker = worker
    worker.start()


def on_live_feed_settings_changed(self):
    """Connected to each settings combo's currentIndexChanged in app.py. Guarded
    by _live_feed_ready so combo population itself (before the page has
    actually been entered) doesn't trigger a preview start, and skipped
    entirely mid-recording since changing the camera out from under an
    active VideoWriter would corrupt the take."""
    if getattr(self, "_live_feed_ready", False) and not getattr(self, "_is_recording", False):
        _start_camera_preview(self)


def reposition_playback_button(self):
    """Keeps the playback overlay button pinned to liveFeedLabel's bottom-right
    corner -- called from MainWindow.resizeEvent and whenever the button's
    visibility changes, since liveFeedLabel's size isn't stable until the
    page's layout has actually been applied."""
    label = getattr(self, "liveFeedLabel", None)
    btn = getattr(self, "btnPlayback", None)
    if not label or not btn:
        return
    btn.adjustSize()
    margin = 12
    btn.move(max(0, label.width() - btn.width() - margin),
             max(0, label.height() - btn.height() - margin))


def liveFeedPageEnter(self):
    """Called when Page 4's Record Video button navigates to the Live Feed
    page. Safe to call again on a later re-visit (e.g. after Redo takes the
    student back through Page 3)."""
    self._is_recording = False
    self._has_recording = False
    if self.btnRecord:
        self.btnRecord.setEnabled(True)
    if self.btnStop:
        self.btnStop.setEnabled(False)
    if self.btnRepeatLive:
        self.btnRepeatLive.setEnabled(False)
    if self.btnNextLive:
        self.btnNextLive.setEnabled(False)
    if self.btnPlayback:
        self.btnPlayback.setText("▶ Play")
        self.btnPlayback.hide()
    for combo in (self.cameraCombo, self.resolutionCombo, self.fpsCombo):
        if combo:
            combo.setEnabled(True)
    if self.lblLiveFeedStatus:
        self.lblLiveFeedStatus.setText(_live_feed_status_html("Ready to record."))

    _populate_live_feed_combos(self)
    self._live_feed_ready = True
    _start_camera_preview(self)


def liveFeedPageLeave(self):
    """Releases the camera device and stops any playback loop. Called before
    navigating forward via Next, and from MainWindow.closeEvent so the app
    never exits with the camera still open."""
    self._live_feed_ready = False
    _stop_camera_worker(self)
    _stop_playback_worker(self)


def startRecording(self):
    worker = getattr(self, "_cameraWorker", None)
    if worker is None:
        # No live camera yet -- most likely it wasn't available when the page
        # was entered (another app had it open). Live Feed has no "back to
        # Page 4" button to otherwise retry from, so Record itself retries
        # detection once instead of silently doing nothing.
        _refresh_camera_list(self)
        _start_camera_preview(self)
        worker = getattr(self, "_cameraWorker", None)
        if worker is None:
            return  # status label already explains why (_start_camera_preview)
    self._is_recording = True
    worker.start_recording()

    self.btnRecord.setEnabled(False)
    self.btnStop.setEnabled(True)
    self.btnRepeatLive.setEnabled(False)
    self.btnNextLive.setEnabled(False)
    self.btnPlayback.hide()
    for combo in (self.cameraCombo, self.resolutionCombo, self.fpsCombo):
        combo.setEnabled(False)
    self.lblLiveFeedStatus.setText(_live_feed_status_html("Recording..."))


def stopRecording(self):
    worker = getattr(self, "_cameraWorker", None)
    if worker is None:
        return
    self._is_recording = False
    self.btnStop.setEnabled(False)
    worker.stop_recording()  # -> recording_finished signal -> _recording_finished


def _recording_finished(self, measured_fps, frame_count):
    self._has_recording = True
    if self.btnRepeatLive:
        self.btnRepeatLive.setEnabled(True)
    if self.btnNextLive:
        self.btnNextLive.setEnabled(True)
    if self.btnPlayback:
        self.btnPlayback.show()
        reposition_playback_button(self)

    duration_s = frame_count / measured_fps if measured_fps else 0.0
    if self.lblLiveFeedStatus:
        self.lblLiveFeedStatus.setText(_live_feed_status_html(
            f"Recorded {duration_s:.1f}s &middot; {frame_count} frames &middot; "
            f"{measured_fps:.1f} fps measured."
        ))

    # Same properties select_video_file() sets for an uploaded file, at the
    # same destination path -- generate()/genData() on Page 5 don't need to
    # know or care which pipeline produced this video.
    self.video_path = self.path / "Recording.mp4"
    self.parent_path = self.video_path.parent
    if measured_fps and measured_fps > 0:
        self.fps_eff = measured_fps


def repeatRecording(self):
    """Discards the current take and goes back to the pre-Record state,
    resuming the live camera view."""
    _stop_playback_worker(self)
    self._has_recording = False
    if self.btnRepeatLive:
        self.btnRepeatLive.setEnabled(False)
    if self.btnNextLive:
        self.btnNextLive.setEnabled(False)
    if self.btnRecord:
        self.btnRecord.setEnabled(True)
    if self.btnPlayback:
        self.btnPlayback.setText("▶ Play")
        self.btnPlayback.hide()
    for combo in (self.cameraCombo, self.resolutionCombo, self.fpsCombo):
        if combo:
            combo.setEnabled(True)
    if self.lblLiveFeedStatus:
        self.lblLiveFeedStatus.setText(_live_feed_status_html("Ready to record."))
    _start_camera_preview(self)


def togglePlayback(self):
    """The overlay button on top of the video area: plays the just-recorded
    take back, or stops an in-progress playback early. Never runs at the same
    time as the live camera loop -- one or the other owns liveFeedLabel."""
    if getattr(self, "_playbackWorker", None) is not None:
        _stop_playback_worker(self)
        self.btnPlayback.setText("▶ Play")
        _start_camera_preview(self)
        return

    _stop_camera_worker(self)
    worker = camf.PlaybackWorker(self.path / "Recording.mp4")
    worker.frame_ready.connect(self._on_playback_frame)
    worker.finished_playback.connect(self._on_playback_finished)
    self._playbackWorker = worker
    self.btnPlayback.setText("■ Stop")
    worker.start()


def _playback_finished(self):
    """Fires both when playback runs to the end of the file on its own and
    when the user clicked Stop -- togglePlayback's explicit-stop path already
    reset the button/resumed the preview by the time this runs in that case,
    so this only needs to cover the natural-end path; re-checking
    _playbackWorker here (still set to the just-finished worker at this
    point, since togglePlayback's explicit-stop branch clears it first)
    avoids double-resuming the preview."""
    if getattr(self, "_playbackWorker", None) is None:
        return
    self._playbackWorker = None
    self.btnPlayback.setText("▶ Play")
    _start_camera_preview(self)


def _camera_error(self, message):
    print(f"[ERROR] Camera: {message}")
    if self.lblLiveFeedStatus:
        self.lblLiveFeedStatus.setText(_live_feed_status_html(f"Camera error: {message}"))


def _show_live_frame(self, qimage):
    """Shared by both the live camera preview and file playback -- both feed
    liveFeedLabel the same way, just from different worker signals."""
    if not self.liveFeedLabel:
        return
    pixmap = QPixmap.fromImage(qimage)
    scaled = pixmap.scaled(self.liveFeedLabel.size(), Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
    self.liveFeedLabel.setPixmap(scaled)



def _load_scaled_image(self, filename, target_size):
    """
    Loads Images/<filename> and scales it to target_size at the window's
    actual device pixel ratio (shared by _load_logo and the Page 2 plan
    images) instead of just scaling to target_size's logical pixels --
    otherwise the image looks soft/low-resolution on HiDPI displays, since
    Qt would then have to upscale an already-downscaled bitmap to fill the
    physical pixel grid.
    """
    dpr = self.devicePixelRatioF()
    device_size = QSize(int(target_size.width() * dpr), int(target_size.height() * dpr))
    pixmap = QPixmap(str(resource_path("Images", filename)))
    scaled = pixmap.scaled(device_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    scaled.setDevicePixelRatio(dpr)
    return scaled


# Page 2 plan images (Images/page2_N.png) render at this logical size, then
# get scaled down (KeepAspectRatio) to whatever their placeholder label ends
# up sized to by the layout -- raise/lower this to change how large they show.
PLAN_IMAGE_SIZE = QSize(480, 360)


def load_plan_images(self):
    """
    Fills the Page 2 image placeholders with their real images. Currently
    only planImagePlaceholder2 (the bottom one) has an image -- page2_1.png.
    To add the top one, drop a file in Images/ and add a matching block for
    planImagePlaceholder1 here.
    """
    if getattr(self, "planImagePlaceholder2", None) is not None:
        pixmap = _load_scaled_image(self, "page2_1.png", PLAN_IMAGE_SIZE)
        self.planImagePlaceholder2.setScaledContents(False)
        self.planImagePlaceholder2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.planImagePlaceholder2.setPixmap(pixmap)
        self.planImagePlaceholder2.setStyleSheet("")
        self.planImagePlaceholder2.setText("")


def scaler(self):
    # Each of these defaults to self.target_size (set in app.py). Give
    # either its own QSize(...) here to resize just that logo independently.
    istlogo1_size = QSize(400, 200)
    istlogo6_size = QSize(400, 200)

    self.istlogo1.setScaledContents(False)
    self.istlogo1.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.istlogo1.setPixmap(_load_scaled_image(self, "logoIST.png", istlogo1_size))

    self.istlogo6.setScaledContents(False)
    self.istlogo6.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.istlogo6.setPixmap(_load_scaled_image(self, "logoIST.png", istlogo6_size))