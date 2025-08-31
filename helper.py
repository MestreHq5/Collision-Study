from pathlib import Path
import os


def file_manager(parent_folder: str, child_folder: str) -> Path:
    """
    On Windows: create Desktop/parent_folder and /child_folder if not exists.
    Return the Path to the child folder.
    """
    # 1. Desktop path
    desktop = Path(os.path.expanduser("~")) / "Desktop"

    # 2. Main folder
    base = desktop / parent_folder
    base.mkdir(parents=True, exist_ok=True)

    # 3. Subfolder
    sub = base / str(child_folder)
    sub.mkdir(parents=True, exist_ok=True)

    # 4. Return full path
    return sub


# ---------------------------
# Camera / Recording Controls
# ---------------------------

# hp.camera_open(...)
def camera_open(controller):
    if hasattr(controller, "worker") and not controller.worker.isRunning():
        controller.worker.start()

    # arriving to camera page: lock controls until preview is real
    controller.preview_ready = False
    controller.btnRecord.setEnabled(False)
    controller.btnStop.setEnabled(False)
    controller.btnNext4.setEnabled(False)
    return

# hp.on_record(...)
def on_record(controller):
    # hard guard in case someone re-enables the button accidentally
    if not getattr(controller, "preview_ready", False):
        return  # no stream yet, ignore

    video_path = controller.path / "Recording.mp4"
    controller.worker.start_record(video_path)
    controller.btnRecord.setEnabled(False)
    controller.btnStop.setEnabled(True)
    controller.btnNext4.setEnabled(False)
    return



def on_stop(controller):
    """
    Stop recording; keep preview running.
    Re-enable Record and Next; disable Stop.
    """
    if hasattr(controller, "worker") and controller.worker.isRunning():
        controller.worker.stop_record()

    # Button Logic
    controller.btnRecord.setEnabled(True)
    controller.btnStop.setEnabled(False)
    controller.btnNext4.setEnabled(True)

    return


# ---------------------------
# Validation & Helpers
# ---------------------------

def validate_input(group, massB, massG, radiusB, radiusG):
    # Check the Input Values
    message = ""

    if group is not None and group != "":
        group = str(group)
    else:
        message = "GRUPO INVÁLIDO"
        return message

    try:
        massB = float(massB)
    except ValueError:
        message = "MASSA DO DISCO AZUL INVÁLIDA"
        return message

    try:
        massG = float(massG)
    except ValueError:
        message = "MASSA DO DISCO VERDE INVÁLIDA"
        return message

    try:
        radiusB = float(radiusB)
    except ValueError:
        message = "RAIO DO DISCO AZUL INVÁLIDO"
        return message

    try:
        radiusG = float(radiusG)
    except ValueError:
        message = "RAIO DO DISCO VERDE INVÁLIDO"
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

    message = validate_input(
        group_val, blue_mass_val, green_mass_val, blue_rad_val, green_rad_val
    )

    if message == "":
        # Move to camera page (index 3)
        self.stack.setCurrentIndex(3)

        # Prepare save path and start preview
        self.path = file_manager("Collision_Study", group_val)
        camera_open(self)

    else:
        self.warning_Label.setText(message)
        eraser(self)

    return
