# Default Imports from PySide6 and the Qt framework

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QPushButton, QLabel, QLineEdit
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QObject, Signal, Slot
import os


# Personal Imports for wiring navigation
import helper as hp


class Controller(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Load UI
        loader = QUiLoader()
        f = QFile("gui.ui"); f.open(QFile.ReadOnly)
        self.ui = loader.load(f, self); f.close()
        self.setCentralWidget(self.ui)


        # Identify Widgets used in the Qt Designer ---> Done by page so it's easier to work
        
        # Global
        self.stack: QStackedWidget = self.ui.findChild(QStackedWidget, "stack")
        
        # Page 1
        self.title1: QLabel = self.ui.findChild(QLabel, "title1")
        self.subtitle1: QLabel = self.ui.findChild(QLabel, "subtitle1")
        self.btnStart: QPushButton = self.ui.findChild(QPushButton, "btnStart")
        
        # Page 2
        self.instructions: QLabel = self.ui.findChild(QLabel, "instructions")
        self.btnNext2: QPushButton = self.ui.findChild(QPushButton, "btnNext2")
        
        # Page 3
        self.group: QLabel = self.ui.findChild(QLabel, "group")
        self.group_val: QLineEdit = self.ui.findChild(QLineEdit, "group_val")
        self.green_mass: QLabel = self.ui.findChild(QLabel, "disk_m_g")
        self.green_mass_val: QLineEdit = self.ui.findChild(QLineEdit, "disk_m_g_val")
        self.blue_mass: QLabel = self.ui.findChild(QLabel, "disk_m_b")
        self.blue_mass_val: QLineEdit = self.ui.findChild(QLineEdit, "disk_m_b_val")
        self.green_rad: QLabel = self.ui.findChild(QLabel, "disk_r_g")
        self.green_rad_val: QLineEdit = self.ui.findChild(QLineEdit, "disk_r_g_val")
        self.blue_rad: QLabel = self.ui.findChild(QLabel, "disk_r_b")
        self.blue_rad_val: QLineEdit = self.ui.findChild(QLineEdit, "disk_r_b_val")
        
        self.btnValidate: QPushButton = self.ui.findChild(QPushButton, "validate")
        
        
        # Inputs --> Page 3 
        group = self.group.text()
        group_val = self.group
        
        
        # Connect navigation ---> Done by page so it's easier to work
        self.btnStart.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        self.btnNext2.clicked.connect(lambda: self.stack.setCurrentIndex(2))
        
        self.btnValidate.clicked.connect(lambda: hp.validate_input())
   
        # Start at page 0
        self.stack.setCurrentIndex(0)



# Initialize the App
def main():
    app = QApplication([])
    app.setStyle("Fusion") 
    win = Controller()
    win.ui.show()
    app.exec()

