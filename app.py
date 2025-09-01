# Default Imports from PySide6 and the Qt framework

import sys
import time
from PyQt6 import uic
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton, QStackedWidget, QLineEdit, QStatusBar

# Block Warnings from MSMF
import os
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"  # or "ERROR"

import cv2
try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except Exception:
    pass


# Personal Imports for wiring navigation
import helper as hp
from pathlib import Path


class CameraWorker(QThread):
    ImageUpdate = pyqtSignal(QImage)
    ConfigReady = pyqtSignal(int, int, float, str)  # width, height, fps, backend_name
    StatsUpdate = pyqtSignal(float) 

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self._active = False
        self._camera_index = camera_index
        self._t0 = None
        self._frame_count = 0

        # recording state
        self._recording = False
        self._writer = None
        self._target_fps = None
        self._size = None          # (width, height)
        self._path = None

        self._config_emitted = False
        self._backend_used = 'unknown'

        # Silence OpenCV warnings (e.g., MSMF warn lines)
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except Exception:
            pass

    # ---------- internals ----------

    def _open_with_backend(self, backend_name: str):
        """backend_name in {'dshow','msmf','any'}"""
        code = {
            'dshow': getattr(cv2, 'CAP_DSHOW', 700),
            'msmf' : getattr(cv2, 'CAP_MSMF', 0),
            'any'  : cv2.CAP_ANY
        }[backend_name]
        cap = cv2.VideoCapture(self._camera_index, code)
        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def _try_configure(self, cap):
        """
        Try largest → smaller at 60 fps, then at 30 fps.
        Accept the first combo that yields frames reasonably close to the ask.
        """
        prefs = (
            [(3840, 2160, 60), (2560, 1440, 60), (1920, 1080, 60), (1280, 720, 60)]
            + [(3840, 2160, 30), (2560, 1440, 30), (1920, 1080, 30), (1280, 720, 30)]
        )
        for w, h, fps in prefs:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            cap.set(cv2.CAP_PROP_FPS,          fps)

            ok, test = cap.read()
            if not ok or test is None:
                continue

            fh, fw = test.shape[:2]
            # accept if reasonably close (USB cams often return near values)
            if abs(fw - w) <= 32 and abs(fh - h) <= 32:
                self._size = (fw, fh)
                self._target_fps = float(fps)
                return True

        # Fallback: whatever camera gives
        ok, test = cap.read()
        if ok and test is not None:
            fh, fw = test.shape[:2]
            self._size = (fw, fh)
            fps_prop = cap.get(cv2.CAP_PROP_FPS)
            if not fps_prop or fps_prop <= 1:
                fps_prop = 30.0
            self._target_fps = float(30 if fps_prop > 30 else int(fps_prop))
            return True
        return False

    def _probe_viable(self, cap, max_frames=8):
        """
        Some DSHOW setups return 'ok' frames that are all black.
        Read a few frames and check that at least one isn't completely black.
        """
        got = 0
        nonblack = 0
        for _ in range(max_frames):
            ok, f = cap.read()
            if not ok or f is None:
                continue
            got += 1
            # If ALL pixels are zero, this returns 0 (definitely black)
            gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            if cv2.countNonZero(gray) > 0:
                nonblack += 1
            if got >= 3:  # enough to judge
                break
        return got >= 1 and nonblack >= 1

    def _emit_config_once(self, cap):
        if self._config_emitted or self._size is None:
            return
        w, h = int(self._size[0]), int(self._size[1])
        fps = float(self._target_fps or cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.ConfigReady.emit(w, h, fps, self._backend_used)
        self._config_emitted = True

    # ---------- thread main ----------

    def run(self):
        self._active = True

        # Order: try DSHOW first; if not viable, fall back to MSMF; finally ANY
        order = ['msmf', 'dshow', 'any']
        cap = None
        try:
            for be in order:
                c = self._open_with_backend(be)
                if c is None:
                    continue
                if not self._try_configure(c):
                    c.release()
                    continue
                # ensure backend is actually giving non-black frames
                if not self._probe_viable(c):
                    c.release()
                    continue

                cap = c
                self._backend_used = be
                break

            if cap is None:
                return  # no camera available

            # announce configuration (size/fps/backend)
            self._emit_config_once(cap)
            self._t0 = time.time()
            self._frame_count = 0

            # main loop
            while self._active:
                ok, frame_bgr = cap.read()
                if not ok:
                    continue

                if self._size is None:
                    h, w = frame_bgr.shape[:2]
                    self._size = (w, h)
                    self._emit_config_once(cap)

                # preview (mirror horizontally for user view)
                rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                rgb = cv2.flip(rgb, 1)
                h, w, ch = rgb.shape
                qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
                self.ImageUpdate.emit(qimg)

                # recording (write original orientation)
                if self._recording and self._writer is not None:
                    self._writer.write(frame_bgr)
                    
                self._frame_count += 1
                now = time.time()
                if now - self._t0 >= 2.0:  # 2-second window
                    fps_eff = self._frame_count / (now - self._t0)
                    self.StatsUpdate.emit(fps_eff)
                    self._t0 = now
                    self._frame_count = 0

        finally:
            if self._writer is not None:
                self._writer.release()
                self._writer = None
            if cap is not None:
                cap.release()

    # ---------- recording API ----------

    def start_record(self, path, fps=None):
        """
        Start video-only recording to `path`. Overwrites previous recording.
        Writes MP4 (mp4v); falls back to AVI (MJPG) if needed.
        """
        if self._size is None:
            self._size = (1920, 1080)
        if fps is None:
            fps = float(self._target_fps or 30)

        # close previous writer (overwrite policy)
        if self._writer is not None:
            self._writer.release()
            self._writer = None

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        w, h = int(self._size[0]), int(self._size[1])

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(p), fourcc, float(fps), (w, h))

        if not writer.isOpened():
            # fallback to AVI MJPG with same basename
            avi_path = p.with_suffix(".avi")
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            writer = cv2.VideoWriter(str(avi_path), fourcc, float(fps), (w, h))
            if writer.isOpened():
                self._path = avi_path
            else:
                return  # give up; do not enter recording state
        else:
            self._path = p

        self._writer = writer
        self._recording = True

    def stop_record(self):
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        self._recording = False

    # ---------- stop thread ----------

    def stop(self):
        self._active = False
        self.wait(500)



class MainWindow(QMainWindow):
    def __init__(self):
        # Initialize and Load the GUI
        super().__init__()
        uic.loadUi("gui.ui", self)  
        self.resize(self.width(), self.height() + 20)

        # --- Identify Widgets used in the Qt Designer ---> Done by page so it's easier to work ---
        # Global
        self.stack: QStackedWidget = self.findChild(QStackedWidget, "stack")
        self.showUpdate = False

        # Page 1
        self.title1: QLabel = self.findChild(QLabel, "title1")
        self.subtitle1: QLabel = self.findChild(QLabel, "subtitle1")
        self.btnStart: QPushButton = self.findChild(QPushButton, "btnStart")

        # Page 2
        self.instructions: QLabel = self.findChild(QLabel, "instructions")
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
        self.videoLabel: QLabel = self.findChild(QLabel, "videoLabel")
        self.btnRecord: QPushButton = self.findChild(QPushButton, "btnRecord")
        self.btnStop: QPushButton = self.findChild(QPushButton, "btnStop")
        self.btnNext4: QPushButton = self.findChild(QPushButton, "btnNext4")
        
        # Page 5
        self.trajectoriesLabel: QLabel = self.findChild(QLabel, "trajectoriesLabel") 
        self.btnRedo: QPushButton = self.findChild(QPushButton, "btnRedo") 
        self.btnNext5: QPushButton = self.findChild(QPushButton, "btnNext5")


        # Connect navigation ---> (Safeguards against bad widget connection)
        if self.btnStart and self.stack:
            self.btnStart.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        if self.btnNext2 and self.stack:
            self.btnNext2.clicked.connect(lambda: self.stack.setCurrentIndex(2))

        if self.btnValidate:
            self.btnValidate.clicked.connect(lambda: hp.validator(self))

        if self.btnRecord:
            self.btnRecord.clicked.connect(lambda: hp.on_record(self))
        if self.btnStop:
            self.btnStop.clicked.connect(lambda: hp.on_stop(self))

        if self.btnNext4 and self.stack:
            self.btnNext4.clicked.connect(lambda: self.stack.setCurrentIndex(4))

        if self.btnRecord:
            self.btnRecord.setEnabled(False)
        if self.btnStop:
            self.btnStop.setEnabled(False)
        if self.btnNext4:
            self.btnNext4.setEnabled(False)
            
        if self.btnRedo and self.stack:
            self.btnRedo.clicked.connect(lambda: self.stack.setCurrentIndex(3)) 
            
        if self.btnNext5 and self.stack:    
            self.btnNext5.clicked.connect(lambda: self.stack.setCurrentIndex(5))
        
        # Start at page 0
        if self.stack:
            self.stack.setCurrentIndex(0)

        # Camera wiring
        if self.videoLabel:
            self.videoLabel.setScaledContents(True)

        self.preview_ready = False
        self.worker = CameraWorker()
        self.worker.ImageUpdate.connect(self.on_image_update)
        self.worker.ConfigReady.connect(self.on_cam_config)
        
        # Create and Update a StatusBar
        self._sb = self.statusBar()
        self.worker.ConfigReady.connect(self.on_cam_config)
        self.worker.StatsUpdate.connect(self.on_cam_stats)
        self._last_cfg_msg = ""

    
    def on_cam_config(self, w, h, fps, backend):
        # Update StatusBar Message
        self._last_cfg_msg = f"Camera: {w}×{h} @ {fps:.1f} fps by {backend.upper()}"
        self._sb.showMessage(self._last_cfg_msg)


    def on_cam_stats(self, fps_eff: float):
        # Effective FPS Display on StatusBar
        self._sb.showMessage(f"{self._last_cfg_msg} | Effective: {fps_eff:.1f} fps", 2000)
        
        if not self.showUpdate:
            print(f"[INFO] {self._last_cfg_msg} | Effective: {fps_eff:.1f}")
            self.showUpdate = True
    
    
    def on_image_update(self, qimage: QImage):
        # Safeguard Against Bugs (bad connection on __init__)
        if not self.videoLabel:
            return
        
        # Convert to a Qt Readable Format
        pix = QPixmap.fromImage(qimage).scaled(self.videoLabel.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.videoLabel.setPixmap(pix)

        # Enable Record once Camera is UP
        if not self.preview_ready:
            self.preview_ready = True
            if self.btnRecord:
                print("[INFO] Camera Started")
                self.btnRecord.setEnabled(True)


    def stop_camera(self):
        # Closes the CameraWorker Thread
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.stop()


    def closeEvent(self, event):
        # Closes Camera Related Events
        self.stop_camera()
        super().closeEvent(event)


# Initialize the App
def main():
    print("[INFO] App Starting")
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

