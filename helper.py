from pathlib import Path
import os
from webcam import WebcamSimple


def file_manager(parent_folder: str, child_folder: str) -> Path:
    """
    On Windows: create Desktop/experience and /group if not exists.
    Return the Path.
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


def on_record(controller):
    if controller.cam is None:
        camera_open(controller)
        controller.btnNext4.setEnabled(False)
        
        
    if not getattr(controller.cam, "recording", False):
        controller.cam.start_record()
        controller.btnRecord.setEnabled(False)
        controller.btnStop.setEnabled(True)
        
    return


def on_stop(controller):
    if controller.cam:
        controller.cam.stop_record()
        controller.cam.close()
        controller.cam = None
        
    # Button Logic    
    controller.btnRecord.setEnabled(True)
    controller.btnStop.setEnabled(False)
    controller.btnNext4.setEnabled(True)
    
    return


def camera_open(self): 
    
    videoPath = self.path / "Recording.avi"
        
    self.cam = WebcamSimple(self.videoLabel, videoPath)
    self.cam.start()

    return
    
    
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
        
        message = validate_input(group_val, blue_mass_val, green_mass_val, blue_rad_val, green_rad_val)
        
        if message == "":
            self.stack.setCurrentIndex(3)
            self.path = file_manager("Collision_Study", group_val)
            camera_open(self)
        
        else:
            self.warning_Label.setText(message)
            eraser(self)
        
        return


