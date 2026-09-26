# Default Imports from PySide6 and the Qt framework
import sys
from PyQt6 import uic
from PyQt6.QtCore import Qt, QSize, QTimer, QEvent
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QPushButton, QStackedWidget, QLineEdit,
    QProgressBar, QPlainTextEdit, QComboBox,
)
from pathlib import Path

# Imports of OpenCV and Operating System
import cv2
import os

# Imports of other Modules for Wiring and Navigation
import helper as hp
import cameraFeed as camf


# Qt6 sets per-monitor-v2 DPI awareness automatically as soon as its platform
# plugin loads (PyQt6 import above already triggered this) — no manual
# SetProcessDpiAwareness call needed. A prior version of this file called it
# here anyway, which Windows only allows once per process; since PyQt6 had
# already set it by this point, the redundant call is what was producing the
# "SetProcessDpiAwarenessContext() failed" warning.

# Now perform your standard imports below
import cv2
import matplotlib
import Post_process


def resource_path(*parts) -> Path:
    """
    Works in dev AND when frozen (PyInstaller onefile/onedir, Nuitka).
    Looks for bundled files in sys._MEIPASS when frozen.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base.joinpath(*parts)


class MainWindow(QMainWindow):
    
    def __init__(self):
        # Initialize and Load the GUI
        super().__init__()
        uic.loadUi(str(resource_path("gui.ui")), self)
        self.target_size = QSize(480, 480)

        # Tee stdout so the deliberately-tagged [INFO]/[WARN]/[ERROR] prints
        # also reach Page 5's genLog box -- see helper.PrintTee. Kept on
        # self so it isn't garbage-collected; installed here (not main())
        # so line_ready has somewhere to connect to as soon as it exists.
        self._print_tee = hp.PrintTee(sys.stdout)
        sys.stdout = self._print_tee
        self._print_tee.line_ready.connect(self._on_log_line)

        self.setMinimumSize(742, 555)  # the .ui's original design size -- below
        # this, the redesigned pages' layouts get cramped rather than
        # reflowing usefully. Actual startup size/state is maximized,
        # applied via showMaximized() in main() -- this floor only matters
        # if the user later un-maximizes the window.

        # Global
        self.stack: QStackedWidget = self.findChild(QStackedWidget, "stack")

        # Page 1
        self.title1: QLabel = self.findChild(QLabel, "title1")
        self.subtitle1: QLabel = self.findChild(QLabel, "subtitle1")
        self.istlogo1: QLabel = self.findChild(QLabel, "istlogo1")
        self.btnStart: QPushButton = self.findChild(QPushButton, "btnStart")

        # Page 2
        self.btnNext2: QPushButton = self.findChild(QPushButton, "btnNext2")
        self.planImagePlaceholder1: QLabel = self.findChild(QLabel, "planImagePlaceholder1")
        self.planImagePlaceholder2: QLabel = self.findChild(QLabel, "planImagePlaceholder2")

        # Page 3
        self.group: QLabel = self.findChild(QLabel, "group")
        self.group_val: QLineEdit = self.findChild(QLineEdit, "group_val")
        self.green_mass: QLabel = self.findChild(QLabel, "disk_m_g")
        self.green_mass_val: QLineEdit = self.findChild(QLineEdit, "disk_m_g_val")
        self.blue_mass: QLabel = self.findChild(QLabel, "disk_m_b")
        self.blue_mass_val: QLineEdit = self.findChild(QLineEdit, "disk_m_b_val")
        self.green_rad: QLabel = self.findChild(QLabel, "disk_r_g")
        self.green_rad_val: QLineEdit = self.findChild(QLineEdit, "disk_r_g_val")
        self.blue_rad: QLabel = self.findChild(QLabel, "disk_r_b")
        self.blue_rad_val: QLineEdit = self.findChild(QLineEdit, "disk_r_b_val")
        self.btnValidate: QPushButton = self.findChild(QPushButton, "validate")
        self.warning_Label: QLabel = self.findChild(QLabel, "warning")

        # Page 4
        self.lblUploadStatus: QLabel = self.findChild(QLabel, "lblUploadStatus")
        self.btnSelectFile: QPushButton = self.findChild(QPushButton, "btnSelectFile")
        self.btnRecordVideo: QPushButton = self.findChild(QPushButton, "btnRecordVideo")
        self.btnProceed: QPushButton = self.findChild(QPushButton, "btnProceed")

        # Page "Live Feed" -- inserted between Page 4 (Upload) and Page 5
        # (Analysis/Generate), so every stack index from Page 5 onward is one
        # higher than it used to be (Page 5: 4->5, Page 6: 5->6).
        self.cameraCombo: QComboBox = self.findChild(QComboBox, "cameraCombo")
        self.resolutionCombo: QComboBox = self.findChild(QComboBox, "resolutionCombo")
        self.fpsCombo: QComboBox = self.findChild(QComboBox, "fpsCombo")
        self.liveFeedLabel: QLabel = self.findChild(QLabel, "liveFeedLabel")
        self.lblLiveFeedStatus: QLabel = self.findChild(QLabel, "lblLiveFeedStatus")
        self.btnRecord: QPushButton = self.findChild(QPushButton, "btnRecord")
        self.btnStop: QPushButton = self.findChild(QPushButton, "btnStop")
        self.btnRepeatLive: QPushButton = self.findChild(QPushButton, "btnRepeatLive")
        self.btnNextLive: QPushButton = self.findChild(QPushButton, "btnNextLive")

        # Playback overlay button ("on top of the video" per USER Request) --
        # not in gui.ui: Qt Designer layouts don't support one widget sitting
        # on top of another cleanly (see CLAUDE.md's Qt/uic gotchas), so this
        # is a plain child of liveFeedLabel itself, positioned in the label's
        # own coordinate space by hp.reposition_playback_button (called from
        # resizeEvent and whenever the button's visibility changes).
        self.btnPlayback = QPushButton("▶ Play", self.liveFeedLabel)
        self.btnPlayback.setStyleSheet(
            "QPushButton { color: white; background-color: rgba(0,0,0,150); "
            "border-radius: 8px; padding: 6px 14px; font-weight: bold; } "
            "QPushButton:hover { background-color: rgba(0,0,0,200); }"
        )
        self.btnPlayback.hide()

        # Changing camera/resolution/fps mid-visit restarts the live preview
        # with the new settings -- helper.on_live_feed_settings_changed is a
        # no-op until liveFeedPageEnter has actually run once (guards against
        # the combos' own initial population firing this).
        for combo in (self.cameraCombo, self.resolutionCombo, self.fpsCombo):
            if combo is not None:
                combo.currentIndexChanged.connect(lambda _=None: hp.on_live_feed_settings_changed(self))

        if self.btnRecordVideo and self.stack:
            self.btnRecordVideo.clicked.connect(lambda: (
                self.stack.setCurrentIndex(4),
                hp.liveFeedPageEnter(self),
            ))

        # Page 5
        self.detectionLabel: QLabel = self.findChild(QLabel, "detectionLabel")
        self.progressGen: QProgressBar = self.findChild(QProgressBar, "progressGen")
        self.genLog: QPlainTextEdit = self.findChild(QPlainTextEdit, "genLog")
        self.btnGen: QPushButton = self.findChild(QPushButton, "btnGen")
        self.btnPreview: QPushButton = self.findChild(QPushButton, "btnPreview")
        self.btnRedo: QPushButton = self.findChild(QPushButton, "btnRedo") 
        self.btnNext5: QPushButton = self.findChild(QPushButton, "btnNext5")
        
        # Page 6
        self.istlogo6: QLabel = self.findChild(QLabel, "istlogo6")

        # Tracking variables
        self.video_path = None
        self.parent_path = None
        self.fps_eff = 30.0

        # Live Feed page state (cameraFeed.py workers + page-ready guard --
        # see helper.py's "Page Live Feed" section)
        self._cameraWorker = None
        self._playbackWorker = None
        self._is_recording = False
        self._has_recording = False
        self._live_feed_ready = False
        self._camera_devices = []

        # Image Work (Size IST Logo)
        hp.scaler(self)
        hp.load_plan_images(self)
   
        # Connect navigation
        if self.btnStart and self.stack:
            self.btnStart.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        
        if self.btnNext2 and self.stack:
            self.btnNext2.clicked.connect(lambda: self.stack.setCurrentIndex(2))

        # Page 3 Validation redirects to Page 4 (index 3)
        if self.btnValidate:
            self.btnValidate.clicked.connect(lambda: hp.validator(self))

        # Page 3: Enter/Return advances to the next field in visual (grid)
        # order instead of doing nothing, so a student can fill the form
        # without reaching for the mouse; Enter on the last field submits.
        page3_field_chain = [
            self.group_val, self.green_mass_val, self.green_rad_val,
            self.blue_mass_val, self.blue_rad_val,
        ]
        for field, next_field in zip(page3_field_chain, page3_field_chain[1:]):
            if field and next_field:
                field.returnPressed.connect(next_field.setFocus)
        if page3_field_chain[-1] and self.btnValidate:
            page3_field_chain[-1].returnPressed.connect(self.btnValidate.click)

        # Page 3: Up/Down arrows also move focus along the same chain (Up ->
        # previous field, Down -> next field), same order as the Enter chain
        # above. QLineEdit doesn't expose arrow keys as a signal the way it
        # does returnPressed, so this needs an eventFilter (see
        # MainWindow.eventFilter below) rather than a direct connect.
        self._page3_field_chain = [f for f in page3_field_chain if f]
        for field in self._page3_field_chain:
            field.installEventFilter(self)

        # Page 4 Upload & File Selection Actions
        if self.btnSelectFile:
            self.btnSelectFile.clicked.connect(self.select_video_file)
        if self.btnProceed and self.stack:
            # Single connection (a prior version of this line was connected
            # twice, once here and once earlier in __init__, to two different
            # lambdas that raced each other over the stack index -- the net
            # effect happened to land correctly only because of connection
            # order, see git history). Page 5 (Analysis/Generate) is index 5
            # now that Page "Live Feed" sits between it and Page 4.
            self.btnProceed.clicked.connect(lambda: (
                self.stack.setCurrentIndex(5),
                hp.analisysPage(self),
            ))

        # Page "Live Feed" Actions
        if self.btnRecord:
            self.btnRecord.clicked.connect(lambda: hp.startRecording(self))
        if self.btnStop:
            self.btnStop.clicked.connect(lambda: hp.stopRecording(self))
        if self.btnRepeatLive:
            self.btnRepeatLive.clicked.connect(lambda: hp.repeatRecording(self))
        if self.btnPlayback:
            self.btnPlayback.clicked.connect(lambda: hp.togglePlayback(self))
        if self.btnNextLive and self.stack:
            self.btnNextLive.clicked.connect(lambda: (
                hp.liveFeedPageLeave(self),
                self.stack.setCurrentIndex(5),
                hp.analisysPage(self),
            ))

        # Page 5 Analysis Actions
        if self.btnGen and self.stack:
            self.btnGen.clicked.connect(lambda: (self.btnGen.setEnabled(False), hp.generate(self)))
        if self.btnPreview and self.stack:
            # hp.genData (Excel build + notify_run_complete) now runs
            # automatically in _generation_finished, the same moment this
            # button becomes enabled -- clicking Preview only needs to
            # render the trajectory plot at this point.
            self.btnPreview.clicked.connect(lambda: hp.preview(self))
        if self.btnRedo and self.stack:
            self.btnRedo.clicked.connect(lambda: hp.redo(self))
        if self.btnNext5 and self.stack:
            self.btnNext5.clicked.connect(lambda: self.stack.setCurrentIndex(6))
            
        if self.btnPreview and self.stack:
            self.btnPreview.setEnabled(False)
        if self.btnRedo and self.stack:
            self.btnRedo.setEnabled(False)
        if self.btnNext5 and self.stack: 
            self.btnNext5.setEnabled(False)
            
        # Start at page 0
        if self.stack:
            self.stack.setCurrentIndex(0)

    def eventFilter(self, obj, event):
        """
        Page 3: Up/Down arrows move focus along `_page3_field_chain` (Up ->
        previous field, Down -> next), mirroring the Enter-chain order set up
        in __init__. Installed per-field rather than overriding each
        QLineEdit's own keyPressEvent since these are stock QLineEdit
        instances from gui.ui, not a custom subclass.
        """
        chain = getattr(self, "_page3_field_chain", None)
        if chain and obj in chain and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                idx = chain.index(obj)
                step = -1 if key == Qt.Key.Key_Up else 1
                target = idx + step
                if 0 <= target < len(chain):
                    chain[target].setFocus()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        """
        Re-renders the trajectory preview (if one exists) from its stored
        full-resolution source at the new size -- otherwise the plot stays
        pinned at whatever size it happened to be generated at (the .ui's
        original 742x535-ish default) even once the window grows, defeating
        the point of the window being resizable to begin with.

        Debounced (QTimer.singleShot, restarted on every event) rather than
        applied immediately: a live interactive resize (dragging the window
        edge) fires this dozens of times a second, and doing the pixmap
        rescale synchronously on every single one of those -- while Qt is
        itself still mid-resize, reallocating this window's backing store --
        is a known trigger for "QPainter::...: Painter not active" spam:
        forcing an immediate repaint of a large pixmap on a widget whose
        paint device is actively being resized underneath it. Waiting until
        resize events stop arriving for a short interval means the rescale
        (and its repaint) only actually runs once, after the drag settles,
        against a stable widget -- also strictly faster, since it's no
        longer rescaling a 3600x2400 source image on every intermediate
        frame of the drag.
        """
        super().resizeEvent(event)
        if not hasattr(self, "_trajectory_resize_timer"):
            self._trajectory_resize_timer = QTimer(self)
            self._trajectory_resize_timer.setSingleShot(True)
            self._trajectory_resize_timer.timeout.connect(lambda: hp.apply_trajectory_pixmap(self))
        self._trajectory_resize_timer.start(120)

        # Cheap (just a .move() on a small button), so unlike the trajectory
        # pixmap rescale above this runs on every event rather than debounced.
        hp.reposition_playback_button(self)

    def closeEvent(self, event):
        # Release the camera device / stop any playback loop cleanly instead
        # of letting a background QThread get torn down mid-frame -- without
        # this, closing the app while the Live Feed page's camera preview is
        # still running leaves the device locked for whatever opens it next.
        hp.liveFeedPageLeave(self)
        super().closeEvent(event)

    # Thin bound-method wrappers around helper.py's logic, so hp.generate()
    # can connect DetectionWorker's cross-thread signals to genuine QObject
    # methods (required for Qt to correctly queue them onto this, the GUI,
    # thread) instead of a bare lambda -- see hp.generate()'s comment. The
    # CameraWorker/PlaybackWorker signals from cameraFeed.py follow the same
    # rule.
    def _on_gen_progress(self, frame_idx, total_frames):
        hp._update_progress(self, frame_idx, total_frames)

    def _on_gen_finished(self):
        hp._generation_finished(self)

    def _on_gen_failed(self, message):
        hp._generation_failed(self, message)

    def _on_log_line(self, line):
        if self.genLog:
            self.genLog.appendPlainText(line)

    def _on_camera_frame(self, qimage):
        hp._show_live_frame(self, qimage)

    def _on_camera_error(self, message):
        hp._camera_error(self, message)

    def _on_recording_finished(self, measured_fps, frame_count, width, height):
        hp._recording_finished(self, measured_fps, frame_count, width, height)

    def _on_recording_saving(self):
        hp._recording_saving(self)

    def _on_camera_stats(self, width, height, measured_fps):
        hp._camera_stats(self, width, height, measured_fps)

    def _on_playback_frame(self, qimage):
        hp._show_live_frame(self, qimage)

    def _on_playback_finished(self):
        hp._playback_finished(self)

    def select_video_file(self):
            """Opens file explorer, copies the video to workspace, and reads properties."""
            from PyQt6.QtWidgets import QFileDialog
            import shutil
            
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Video",
                "",
                "Video Files (*.mp4 *.avi *.mov *.mkv)"
            )
            
            if file_path:
                print(f"[INFO] Video Selected: {file_path}")
                
                # Use the directory path created earlier by validator()
                dest_path = self.path / "Recording.mp4"
                
                # Copy the file safely to your workspace if it isn't already there
                if Path(file_path).resolve() != dest_path.resolve():
                    shutil.copy(file_path, dest_path)
                
                # Save references to MainWindow properties
                self.video_path = dest_path
                self.parent_path = dest_path.parent
                
                # Read structural container FPS natively
                cap = cv2.VideoCapture(str(dest_path))
                fps = cap.get(cv2.CAP_PROP_FPS)
                cap.release()
                
                if fps <= 0 or not fps:
                    fps = 30.0  # Fallback
                self.fps_eff = fps
                print(f"[INFO] Video Native FPS: {fps}")
                
                # Update Page 4 status message to show successful upload
                video_name = os.path.basename(file_path)
                self.lblUploadStatus.setText(
                    f'<html><body><p align="center"><span style="font-size:24pt; color:#009de0; font-weight:bold;">'
                    f'Loaded: {video_name}<br><span style="font-size:18pt; color:#555555; font-weight:normal;">'
                    f'({fps:.2f} FPS)</span></span></p></body></html>'
                )
                
                # Enable navigation proceed button
                if self.btnProceed:
                    self.btnProceed.setEnabled(True)
            else:
                print("[INFO] Video selection cancelled")


def main():
    print("[INFO] App Starting")
    # Must be the explicit API call, and must happen before QApplication()
    # is constructed -- setting QT_SCALE_FACTOR_ROUNDING_POLICY as an env
    # var instead (a prior version of this file did, via Post_process.py)
    # measurably still fires "setHighDpiScaleFactorRoundingPolicy must be
    # called before creating the QGuiApplication instance" on every launch
    # in this PyQt6 build -- confirmed by bisection that the env var alone,
    # with nothing else in the process, reproduces the warning, while this
    # call does not. QT_ENABLE_HIGHDPI_SCALING/QT_AUTO_SCREEN_SCALE_FACTOR
    # (also previously set as env vars) are Qt5-era flags with no effect in
    # Qt6, where high-DPI scaling is already on by default -- dropped.
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.showMaximized()  # maximized, not full screen -- keeps the title bar/
    # taskbar (normal windowed chrome) while still opening at full usable
    # screen size, per USER Request in ToDo.md.
    sys.exit(app.exec())