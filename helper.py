from pathlib import Path
import re
import sys
import os
import shutil
import cv2
import detector as dtc
import Post_process as ptp
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
        self._sb.showMessage("Data validated. Please select your tracking video.")
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


def _generation_failed(self, message):
    self.btnGen.setEnabled(True)
    self._sb.showMessage(f"Detection failed: {message}")
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
    
    ptp.build_student_excel(csv_path, output_path, masses, radius, fps, include_metrics=True)
    
    self.btnPreview.setEnabled(False)
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
    # Old page index 4 is now index 3 because we deleted the recording page
    self.stack.setCurrentIndex(3)

    
def redo(self):
    # Sends user straight back to data input form to upload a new video file
    self.stack.setCurrentIndex(2)
    

def _load_logo(self, filename):
    """
    Renders the logo at the window's actual device pixel ratio (like
    apply_trajectory_pixmap does for the trajectory preview) instead of just
    scaling to self.target_size's logical pixels -- otherwise the logo looks
    soft/low-resolution on HiDPI displays, since Qt would then have to
    upscale an already-downscaled bitmap to fill the physical pixel grid.
    """
    dpr = self.devicePixelRatioF()
    device_size = QSize(int(self.target_size.width() * dpr), int(self.target_size.height() * dpr))
    pixmap = QPixmap(str(resource_path("Images", filename)))
    scaled = pixmap.scaled(device_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    scaled.setDevicePixelRatio(dpr)
    return scaled


def scaler(self):
    ist_logo = _load_logo(self, "logoIST.png")
    dem_logo = _load_logo(self, "logoDEM.png")

    self.istlogo1.setScaledContents(False)
    self.istlogo1.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.istlogo1.setPixmap(ist_logo)

    if getattr(self, "istlogo1b", None) is not None:
        self.istlogo1b.setScaledContents(False)
        self.istlogo1b.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.istlogo1b.setPixmap(dem_logo)

    self.istlogo6.setScaledContents(False)
    self.istlogo6.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.istlogo6.setPixmap(ist_logo)