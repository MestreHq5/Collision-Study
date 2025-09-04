from pathlib import Path
import os
import detector as dtc
import Post_process as ptp
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt


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
        # Move to camera page (index 3)
        self.stack.setCurrentIndex(3)

        # Prepare save path and start preview
        self.path = file_manager("Collision_Study", group_val)
        print("[INFO] Valid Inputs")
        camera_open(self)

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
    #csv_path = self.parent_path / "disk_tracks.csv"
    output_path = self.parent_path / "trajectories.png"
    fps = self.worker.fps_eff
    
    # Trajectories Function Call
    csv_path = "C:/Users/gonca/Desktop/disk_tracks.csv"
    ptp.visualize_trajectories(csv_path, output_path, fps, show_equal_aspect=True)
    
    # Button Arithmetic
    self.btnPreview.setEnabled(False)
    self.btnRedo.setEnabled(True)
    self.btnNext5.setEnabled(True)
    
    # Label Preview
    pixmap = QPixmap(str(output_path))
    scaled = pixmap.scaled(self.detectionLabel.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    self.detectionLabel.setPixmap(scaled)
    