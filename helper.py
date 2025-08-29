from pathlib import Path
import os


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


def validate_input(group, massB, massG, radiusB, radiusG):
    message = ""
     
    try:
        group = str(group)
    except ValueError:
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