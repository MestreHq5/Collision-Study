from pathlib import Path
import sys
import os
import shutil
import cv2
import detector as dtc
import Post_process as ptp
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog


def resource_path(*parts) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base.joinpath(*parts)


def file_manager(parent_folder: str, child_folder: str) -> Path:
    desktop = Path(os.path.expanduser("~")) / "Desktop"
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


def generate(self):
    video_path = self.video_path
    parent_path = self.parent_path
    bg_path = parent_path / "table_background.png"
    detection_video_path = parent_path / "detection.mp4"
    csv_path = parent_path / "disk_tracks.csv"
    
    dtc.main(video_path, bg_path, detection_video_path, csv_path, self.fps_eff)
    self.btnPreview.setEnabled(True)


def preview(self):
    csv_path = self.parent_path / "disk_tracks.csv" 
    output_path = self.parent_path / "trajectories.png"
    fps = self.fps_eff
    
    ptp.visualize_trajectories(csv_path, output_path, fps, show_equal_aspect=True)
    
    self.detectionLabel.setScaledContents(False)
    pixmap = QPixmap(str(output_path))
    scaled = pixmap.scaled(self.detectionLabel.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
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

    self.detectionLabel.clear()
    # Old page index 4 is now index 3 because we deleted the recording page
    self.stack.setCurrentIndex(3)

    
def redo(self):
    # Sends user straight back to data input form to upload a new video file
    self.stack.setCurrentIndex(2)
    

def scaler(self):
    logo = QPixmap(str(resource_path("Images", "logoIST.png")))
    scaled = logo.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    
    self.istlogo1.setScaledContents(False) 
    self.istlogo1.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.istlogo1.setPixmap(scaled)
    
    self.istlogo6.setScaledContents(False) 
    self.istlogo6.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.istlogo6.setPixmap(scaled)