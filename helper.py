from pathlib import Path
import sys
import os
import shutil
import cv2
import detector as dtc
import Post_process as ptp
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QMessageBox


def resource_path(*parts) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base.joinpath(*parts)


def file_manager(parent_folder: str, child_folder: str) -> Path:
    # Creates a folder in Desktop and a subfolder for every trial (Ex: Students Groups)

    desktop = Path(os.path.expanduser("~")) / "Desktop"

    base = desktop / parent_folder
    base.mkdir(parents=True, exist_ok=True)

    sub = base / str(child_folder)
    sub.mkdir(parents=True, exist_ok=True)

    return sub


def camera_open(controller):
    # Starts the CameraWorker Thread
    if hasattr(controller, "worker") and not controller.worker.isRunning():
        print("[START] Camera Thread")
        controller.worker.start()

    # Locking Controls untill LiveStream
    controller.preview_ready = False
    controller.btnRecord.setEnabled(False)
    controller.btnStop.setEnabled(False)
    controller.btnNext4.setEnabled(False)
    return


def on_record(controller):
    # Prevent Record while another Record is Running
    if not getattr(controller, "preview_ready", False):
        return  # no stream yet, ignore

    video_path = controller.path / "Recording.mp4"
    controller.worker.start_record(video_path)
    controller.btnRecord.setEnabled(False)
    controller.btnStop.setEnabled(True)
    controller.btnNext4.setEnabled(False)
    return


def on_stop(controller):
    # Stop Record if UP
    if hasattr(controller, "worker") and controller.worker.isRunning():
        controller.worker.stop_record()

    # Button Logic
    controller.btnRecord.setEnabled(True)
    controller.btnStop.setEnabled(False)
    controller.btnNext4.setEnabled(True)
    print("[INFO] Recording Stopped")

    return


def validate_input(group, massB, massG, radiusB, radiusG):
    # Check the Input Values
    message = ""

    if group is not None and group != "":
        group = str(group)
    else:
        message = "INVALID GROUP"
        return message

    try:
        massB = float(massB)
    except ValueError:
        message = "INVALID BLUE DISK MASS"
        return message

    try:
        massG = float(massG)
    except ValueError:
        message = "INVALID GREEN DISK MASS"
        return message

    try:
        radiusB = float(radiusB)
    except ValueError:
        message = "INVALID BLUE DISK RADIUS"
        return message

    try:
        radiusG = float(radiusG)
    except ValueError:
        message = "INVALID GREEN DISK RADIUS"
        return message

    return message


def eraser(self):
    # Set the Text Boxes to their Default Placeholder Text
    self.group_val.setText("")
    self.green_mass_val.setText("")
    self.blue_mass_val.setText("")
    self.green_rad_val.setText("")
    self.blue_rad_val.setText("")
    return


def validator(self):
    # Inputs --> Page 3
    group_val = self.group_val.text()
    green_mass_val = self.green_mass_val.text()
    blue_mass_val = self.blue_mass_val.text()
    green_rad_val = self.green_rad_val.text()
    blue_rad_val = self.blue_rad_val.text()

    message = validate_input(group_val, blue_mass_val, green_mass_val, blue_rad_val, green_rad_val)

    if message == "":
        
        # Ask user for mode
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Video Source Selection")
        msg_box.setText("Would you like to record a live video or submit an existing one?")
        live_btn = msg_box.addButton("Live Record", QMessageBox.ButtonRole.ActionRole)
        upload_btn = msg_box.addButton("Submit Existing", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = msg_box.addButton(QMessageBox.StandardButton.Cancel)
        
        msg_box.exec()
        
        if msg_box.clickedButton() == live_btn:
            # Move to camera page (index 3)
            self.stack.setCurrentIndex(3)
            # Prepare save path and start preview
            self.path = file_manager("Collision_Study", group_val)
            print("[INFO] Valid Inputs - Live Record Mode")
            camera_open(self)
            
        elif msg_box.clickedButton() == upload_btn:
            # Prepare save path
            self.path = file_manager("Collision_Study", group_val)
            
            # File Dialog
            file_path, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Video Files (*.mp4 *.avi *.mov *.mkv)")
            if file_path:
                print(f"[INFO] Video Selected: {file_path}")
                dest_path = self.path / "Recording.mp4"
                
                # Check if source and destination are the same to avoid error
                if Path(file_path).resolve() != dest_path.resolve():
                    shutil.copy(file_path, dest_path)
                
                # Setup Worker for downstream
                self.worker._path = dest_path
                
                # Get FPS
                cap = cv2.VideoCapture(str(dest_path))
                fps = cap.get(cv2.CAP_PROP_FPS)
                cap.release()
                
                if fps <= 0:
                    fps = 30.0 # Fallback
                self.worker.fps_eff = fps
                
                print(f"[INFO] Video FPS: {fps}")
                
                # Skip to analysis page
                analisysPage(self)
            else:
                print("[INFO] Video selection cancelled")
        else:
            print("[INFO] Selection cancelled")
            
    else:
        self.warning_Label.setText(message)
        print(f"[WARN]: {message}")
        eraser(self)

    return


def generate(self):
    video_path = self.worker._path
    parent_path = self.worker._path.parent
    self.parent_path = parent_path
    bg_path = parent_path / "table_background.png"
    detection_video_path = parent_path /"detection.mp4"
    csv_path = parent_path / "disk_tracks.csv"
    
    dtc.main(video_path, bg_path, detection_video_path, csv_path, self.worker.fps_eff)
    self.btnPreview.setEnabled(True)
    return


def preview(self):
    
    # Path Logic
    csv_path = self.parent_path / "disk_tracks.csv" 
    output_path = self.parent_path / "trajectories.png"
    fps = self.worker.fps_eff
    
    # Trajectories Function Call
    ptp.visualize_trajectories(csv_path, output_path, fps, show_equal_aspect=True)
    
    # Label Preview
    self.detectionLabel.setScaledContents(False)
    pixmap = QPixmap(str(output_path))
    scaled = pixmap.scaled(self.detectionLabel.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    self.detectionLabel.setPixmap(scaled)


def genData(self):
    # Path Logic
    csv_path = self.parent_path / "disk_tracks.csv" ###########
    output_path = self.parent_path / "data.xlsx"
    fps = self.worker.fps_eff
    
    # Experimental Values Logic
    green_mass_val = float(self.green_mass_val.text())
    blue_mass_val = float(self.blue_mass_val.text())
    green_rad_val = float(self.green_rad_val.text())
    blue_rad_val = float(self.blue_rad_val.text())
    
    masses = (green_mass_val, blue_mass_val)
    radius = (green_rad_val, blue_rad_val)
    
    # Data Generation 
    ptp.build_student_excel(csv_path, output_path, masses, radius, fps, include_metrics=True)
    
    # Button Arithmetic
    self.btnPreview.setEnabled(False)
    self.btnRedo.setEnabled(True)
    self.btnNext5.setEnabled(True)
    

def analisysPage(self):
    
    # Button Logic
    self.btnGen.setEnabled(True)
    self.btnPreview.setEnabled(False)
    self.btnRedo.setEnabled(False)
    self.btnNext5.setEnabled(False)

    # Page Logic 
    self.detectionLabel.clear()
    self.stack.setCurrentIndex(4)

    
def redo(self):
    
    # Page Logic
    self.stack.setCurrentIndex(3)
    self.btnNext4.setEnabled(False)
    

def scaler(self):
    # Import Logo
    logo = QPixmap(str(resource_path("Images", "logoIST.png")))

    # Scale Contents 
    scaled = logo.scaled(
    self.target_size,
    Qt.AspectRatioMode.KeepAspectRatio,
    Qt.TransformationMode.SmoothTransformation
    )
    
    # Apply to the QLabel's
    self.istlogo1.setScaledContents(False) 
    self.istlogo1.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.istlogo1.setPixmap(scaled)
    
    self.istlogo6.setScaledContents(False) 
    self.istlogo6.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.istlogo6.setPixmap(scaled)
   