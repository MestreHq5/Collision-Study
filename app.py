# Default Imports from PySide6 and the Qt framework
import sys
from PyQt6 import uic
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton, QStackedWidget, QLineEdit
from pathlib import Path

# Imports of OpenCV and Operating System 
import cv2
import os

# Imports of other Modules for Wiring and Navigation
import helper as hp


# ==============================================================================
# MUST BE AT THE VERY FIRST LINES OF YOUR MAIN EXECUTION SCRIPT
# BEFORE ANY OTHER IMPORTS (cv2, matplotlib, etc.)
# ==============================================================================
if sys.platform == "win32":
    import ctypes
    try:
        # Set process to Per-Monitor DPI Aware before Qt initializes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

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
        self.resize(self.width(), self.height() + 20)
        self.target_size = QSize(300, 300)

        # Global
        self.stack: QStackedWidget = self.findChild(QStackedWidget, "stack")

        # Page 1
        self.title1: QLabel = self.findChild(QLabel, "title1")
        self.subtitle1: QLabel = self.findChild(QLabel, "subtitle1")
        self.istlogo1: QLabel = self.findChild(QLabel, "istlogo1")
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
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())