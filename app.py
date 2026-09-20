# Default Imports from PySide6 and the Qt framework
import sys
from PyQt6 import uic
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton, QStackedWidget, QLineEdit, QProgressBar
from pathlib import Path

# Imports of OpenCV and Operating System 
import cv2
import os

# Imports of other Modules for Wiring and Navigation
import helper as hp


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
        self.target_size = QSize(300, 300)

        # Full available height, half the screen's width, docked to the left
        # edge -- meant to sit side-by-side with a terminal on the right
        # (user's own workflow), not fill the screen. Still freely resizable
        # afterwards; this only sets the initial size/position. A floor keeps
        # it from starting cramped on a small/low-res display.
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        if available is not None:
            target_w = max(int(available.width() * 0.5), 742)
            target_h = available.height()
            self.resize(target_w, target_h)
            self.move(available.x(), available.y())
        else:
            self.resize(self.width(), self.height() + 20)
        self.setMinimumSize(742, 555)  # the .ui's original design size -- below
        # this, the redesigned pages' layouts get cramped rather than
        # reflowing usefully.

        # Global
        self.stack: QStackedWidget = self.findChild(QStackedWidget, "stack")

        # Page 1
        self.title1: QLabel = self.findChild(QLabel, "title1")
        self.subtitle1: QLabel = self.findChild(QLabel, "subtitle1")
        self.istlogo1: QLabel = self.findChild(QLabel, "istlogo1")
        self.btnStart: QPushButton = self.findChild(QPushButton, "btnStart")

        # Page 2
        self.btnNext2: QPushButton = self.findChild(QPushButton, "btnNext2")

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
        self.btnProceed: QPushButton = self.findChild(QPushButton, "btnProceed")
        if self.btnProceed and self.stack:
            self.btnProceed.clicked.connect(lambda: (
                self.stack.setCurrentIndex(4),
                hp.analisysPage(self)  
            ))

        # Page 5
        self.detectionLabel: QLabel = self.findChild(QLabel, "detectionLabel")
        self.progressGen: QProgressBar = self.findChild(QProgressBar, "progressGen")
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

        # Image Work (Size IST Logo)
        hp.scaler(self)
   
        # Connect navigation
        if self.btnStart and self.stack:
            self.btnStart.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        
        if self.btnNext2 and self.stack:
            self.btnNext2.clicked.connect(lambda: self.stack.setCurrentIndex(2))

        # Page 3 Validation redirects to Page 4 (index 3)
        if self.btnValidate:
            self.btnValidate.clicked.connect(lambda: hp.validator(self))
        
        # Page 4 Upload & File Selection Actions
        if self.btnSelectFile:
            self.btnSelectFile.clicked.connect(self.select_video_file)
        if self.btnProceed and self.stack:
            self.btnProceed.clicked.connect(lambda: self.stack.setCurrentIndex(4))

        # Page 5 Analysis Actions
        if self.btnGen and self.stack:
            self.btnGen.clicked.connect(lambda: (self.btnGen.setEnabled(False), hp.generate(self)))
        if self.btnPreview and self.stack:
            self.btnPreview.clicked.connect(lambda: (hp.preview(self), hp.genData(self)))
        if self.btnRedo and self.stack:
            self.btnRedo.clicked.connect(lambda: hp.redo(self)) 
        if self.btnNext5 and self.stack:    
            self.btnNext5.clicked.connect(lambda: self.stack.setCurrentIndex(5))
            
        if self.btnPreview and self.stack:
            self.btnPreview.setEnabled(False)
        if self.btnRedo and self.stack:
            self.btnRedo.setEnabled(False)
        if self.btnNext5 and self.stack: 
            self.btnNext5.setEnabled(False)
            
        # Start at page 0
        if self.stack:
            self.stack.setCurrentIndex(0)

        # Create and Update a Simple StatusBar
        self._sb = self.statusBar()
        self._sb.showMessage("Ready. Please submit a tracking video.")

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

    # Thin bound-method wrappers around helper.py's logic, so hp.generate()
    # can connect DetectionWorker's cross-thread signals to genuine QObject
    # methods (required for Qt to correctly queue them onto this, the GUI,
    # thread) instead of a bare lambda -- see hp.generate()'s comment.
    def _on_gen_progress(self, frame_idx, total_frames):
        hp._update_progress(self, frame_idx, total_frames)

    def _on_gen_finished(self):
        hp._generation_finished(self)

    def _on_gen_failed(self, message):
        hp._generation_failed(self, message)

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
                    f'<html><body><p align="center"><span style="font-size:18pt; color:#009de0; font-weight:bold;">'
                    f'Loaded: {video_name}<br><span style="font-size:14pt; color:#555555; font-weight:normal;">'
                    f'({fps:.2f} FPS)</span></span></p></body></html>'
                )
                
                # Enable navigation proceed button
                if self.btnProceed:
                    self.btnProceed.setEnabled(True)
                    
                self._sb.showMessage(f"Loaded: Recording.mp4 @ {fps:.2f} FPS")
            else:
                print("[INFO] Video selection cancelled")
                self._sb.showMessage("File selection canceled.")


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
    win.show()
    sys.exit(app.exec())