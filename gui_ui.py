# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'gui.ui'
##
## Created by: Qt User Interface Compiler version 6.8.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QGridLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(738, 539)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(MainWindow.sizePolicy().hasHeightForWidth())
        MainWindow.setSizePolicy(sizePolicy)
        MainWindow.setStyleSheet(u"")
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.centralwidget.setStyleSheet(u"background-color: white; ")
        self.verticalLayout_2 = QVBoxLayout(self.centralwidget)
        self.verticalLayout_2.setSpacing(0)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(self.centralwidget)
        self.stack.setObjectName(u"stack")
        sizePolicy.setHeightForWidth(self.stack.sizePolicy().hasHeightForWidth())
        self.stack.setSizePolicy(sizePolicy)
        self.stack.setStyleSheet(u"background-color:white;")
        self.Page_1 = QWidget()
        self.Page_1.setObjectName(u"Page_1")
        sizePolicy.setHeightForWidth(self.Page_1.sizePolicy().hasHeightForWidth())
        self.Page_1.setSizePolicy(sizePolicy)
        self.verticalLayout_3 = QVBoxLayout(self.Page_1)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.vertical = QVBoxLayout()
        self.vertical.setSpacing(6)
        self.vertical.setObjectName(u"vertical")
        self.title1 = QLabel(self.Page_1)
        self.title1.setObjectName(u"title1")

        self.vertical.addWidget(self.title1, 0, Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignBottom)

        self.subtitle1 = QLabel(self.Page_1)
        self.subtitle1.setObjectName(u"subtitle1")

        self.vertical.addWidget(self.subtitle1, 0, Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignTop)

        self.btnStart = QPushButton(self.Page_1)
        self.btnStart.setObjectName(u"btnStart")
        self.btnStart.setStyleSheet(u"QPushButton {\n"
"    color: white;\n"
"    background-color: #009de0;\n"
"	border-radius: 10px;\n"
"    padding: 6px 12px;\n"
"	font-weight: bold;\n"
"}\n"
"\n"
"QPushButton:hover {\n"
"    color: white;\n"
"    background-color: #007bb5;  \n"
"}\n"
"\n"
"QPushButton:pressed {\n"
"    color: white;\n"
"    background-color: #005f87;  \n"
"}\n"
"\n"
"QPushButton:disabled {\n"
"    color: #aaaaaa;\n"
"    background-color: #cccccc;\n"
"}\n"
"")
        self.btnStart.setIconSize(QSize(16, 16))

        self.vertical.addWidget(self.btnStart, 0, Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignTop)


        self.verticalLayout_3.addLayout(self.vertical)

        self.stack.addWidget(self.Page_1)
        self.Page_2 = QWidget()
        self.Page_2.setObjectName(u"Page_2")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.Page_2.sizePolicy().hasHeightForWidth())
        self.Page_2.setSizePolicy(sizePolicy1)
        self.verticalLayout_4 = QVBoxLayout(self.Page_2)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.verticalLayout = QVBoxLayout()
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.instructions = QLabel(self.Page_2)
        self.instructions.setObjectName(u"instructions")
        self.instructions.setStyleSheet(u"color: black;\n"
"background-color: white;")

        self.verticalLayout.addWidget(self.instructions)

        self.btnNext2 = QPushButton(self.Page_2)
        self.btnNext2.setObjectName(u"btnNext2")
        self.btnNext2.setStyleSheet(u"QPushButton {\n"
"    color: white;\n"
"    background-color: #009de0;\n"
"	border-radius: 10px;\n"
"    padding: 6px 12px;\n"
"	font-weight: bold;\n"
"}\n"
"\n"
"QPushButton:hover {\n"
"    color: white;\n"
"    background-color: #007bb5;  \n"
"}\n"
"\n"
"QPushButton:pressed {\n"
"    color: white;\n"
"    background-color: #005f87;  \n"
"}\n"
"\n"
"QPushButton:disabled {\n"
"    color: #aaaaaa;\n"
"    background-color: #cccccc;\n"
"}")

        self.verticalLayout.addWidget(self.btnNext2, 0, Qt.AlignmentFlag.AlignHCenter)


        self.verticalLayout_4.addLayout(self.verticalLayout)

        self.stack.addWidget(self.Page_2)
        self.Page_3 = QWidget()
        self.Page_3.setObjectName(u"Page_3")
        sizePolicy.setHeightForWidth(self.Page_3.sizePolicy().hasHeightForWidth())
        self.Page_3.setSizePolicy(sizePolicy)
        self.gridLayoutWidget = QWidget(self.Page_3)
        self.gridLayoutWidget.setObjectName(u"gridLayoutWidget")
        self.gridLayoutWidget.setGeometry(QRect(9, 9, 721, 521))
        self.gridLayout = QGridLayout(self.gridLayoutWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.disk_r_g = QLabel(self.gridLayoutWidget)
        self.disk_r_g.setObjectName(u"disk_r_g")
        sizePolicy.setHeightForWidth(self.disk_r_g.sizePolicy().hasHeightForWidth())
        self.disk_r_g.setSizePolicy(sizePolicy)
        self.disk_r_g.setStyleSheet(u"background-color: white;\n"
"color: black; \n"
"font-weight: bold;\n"
"padding-left: 10px;")

        self.gridLayout.addWidget(self.disk_r_g, 2, 0, 1, 1)

        self.group_val = QLineEdit(self.gridLayoutWidget)
        self.group_val.setObjectName(u"group_val")
        sizePolicy.setHeightForWidth(self.group_val.sizePolicy().hasHeightForWidth())
        self.group_val.setSizePolicy(sizePolicy)
        self.group_val.setStyleSheet(u"background-color: white;\n"
"color: black; \n"
"border: 3px solid #009de0;")

        self.gridLayout.addWidget(self.group_val, 0, 1, 1, 1, Qt.AlignmentFlag.AlignVCenter)

        self.disk_m_b = QLabel(self.gridLayoutWidget)
        self.disk_m_b.setObjectName(u"disk_m_b")
        sizePolicy.setHeightForWidth(self.disk_m_b.sizePolicy().hasHeightForWidth())
        self.disk_m_b.setSizePolicy(sizePolicy)
        self.disk_m_b.setStyleSheet(u"background-color: white;\n"
"color: black; \n"
"font-weight: bold;\n"
"padding-left: 10px;")

        self.gridLayout.addWidget(self.disk_m_b, 3, 0, 1, 1)

        self.disk_m_b_val = QLineEdit(self.gridLayoutWidget)
        self.disk_m_b_val.setObjectName(u"disk_m_b_val")
        sizePolicy.setHeightForWidth(self.disk_m_b_val.sizePolicy().hasHeightForWidth())
        self.disk_m_b_val.setSizePolicy(sizePolicy)
        self.disk_m_b_val.setStyleSheet(u"background-color: white;\n"
"color: black; \n"
"border: 3px solid #009de0;")

        self.gridLayout.addWidget(self.disk_m_b_val, 3, 1, 1, 1, Qt.AlignmentFlag.AlignVCenter)

        self.group = QLabel(self.gridLayoutWidget)
        self.group.setObjectName(u"group")
        sizePolicy.setHeightForWidth(self.group.sizePolicy().hasHeightForWidth())
        self.group.setSizePolicy(sizePolicy)
        self.group.setStyleSheet(u"background-color: white;\n"
"color: black; \n"
"font-weight: bold;\n"
"padding-left: 10px;")

        self.gridLayout.addWidget(self.group, 0, 0, 1, 1)

        self.disk_m_g = QLabel(self.gridLayoutWidget)
        self.disk_m_g.setObjectName(u"disk_m_g")
        sizePolicy.setHeightForWidth(self.disk_m_g.sizePolicy().hasHeightForWidth())
        self.disk_m_g.setSizePolicy(sizePolicy)
        self.disk_m_g.setStyleSheet(u"background-color: white;\n"
"color: black; \n"
"font-weight: bold;\n"
"padding-left: 10px;")

        self.gridLayout.addWidget(self.disk_m_g, 1, 0, 1, 1)

        self.disk_r_b = QLabel(self.gridLayoutWidget)
        self.disk_r_b.setObjectName(u"disk_r_b")
        sizePolicy.setHeightForWidth(self.disk_r_b.sizePolicy().hasHeightForWidth())
        self.disk_r_b.setSizePolicy(sizePolicy)
        self.disk_r_b.setStyleSheet(u"background-color: white;\n"
"color: black; \n"
"font-weight: bold;\n"
"padding-left: 10px;")

        self.gridLayout.addWidget(self.disk_r_b, 4, 0, 1, 1)

        self.disk_m_g_val = QLineEdit(self.gridLayoutWidget)
        self.disk_m_g_val.setObjectName(u"disk_m_g_val")
        sizePolicy.setHeightForWidth(self.disk_m_g_val.sizePolicy().hasHeightForWidth())
        self.disk_m_g_val.setSizePolicy(sizePolicy)
        self.disk_m_g_val.setStyleSheet(u"background-color: white;\n"
"color: black; \n"
"border: 3px solid #009de0;")

        self.gridLayout.addWidget(self.disk_m_g_val, 1, 1, 1, 1, Qt.AlignmentFlag.AlignVCenter)

        self.disk_r_b_val = QLineEdit(self.gridLayoutWidget)
        self.disk_r_b_val.setObjectName(u"disk_r_b_val")
        sizePolicy.setHeightForWidth(self.disk_r_b_val.sizePolicy().hasHeightForWidth())
        self.disk_r_b_val.setSizePolicy(sizePolicy)
        self.disk_r_b_val.setStyleSheet(u"background-color: white;\n"
"color: black; \n"
"border: 3px solid #009de0;")

        self.gridLayout.addWidget(self.disk_r_b_val, 4, 1, 1, 1, Qt.AlignmentFlag.AlignVCenter)

        self.disk_r_g_val = QLineEdit(self.gridLayoutWidget)
        self.disk_r_g_val.setObjectName(u"disk_r_g_val")
        sizePolicy.setHeightForWidth(self.disk_r_g_val.sizePolicy().hasHeightForWidth())
        self.disk_r_g_val.setSizePolicy(sizePolicy)
        self.disk_r_g_val.setStyleSheet(u"background-color: white;\n"
"color: black; \n"
"border: 3px solid #009de0;")

        self.gridLayout.addWidget(self.disk_r_g_val, 2, 1, 1, 1, Qt.AlignmentFlag.AlignVCenter)

        self.validate = QPushButton(self.gridLayoutWidget)
        self.validate.setObjectName(u"validate")
        self.validate.setStyleSheet(u"QPushButton {\n"
"    color: white;\n"
"    background-color: #009de0;\n"
"	border-radius: 10px;\n"
"    padding: 6px 12px;\n"
"	font-weight: bold;\n"
"}\n"
"\n"
"QPushButton:hover {\n"
"    color: white;\n"
"    background-color: #007bb5;  \n"
"}\n"
"\n"
"QPushButton:pressed {\n"
"    color: white;\n"
"    background-color: #005f87;  \n"
"}\n"
"\n"
"QPushButton:disabled {\n"
"    color: #aaaaaa;\n"
"    background-color: #cccccc;\n"
"}")

        self.gridLayout.addWidget(self.validate, 5, 1, 1, 1)

        self.stack.addWidget(self.Page_3)

        self.verticalLayout_2.addWidget(self.stack)

        MainWindow.setCentralWidget(self.centralwidget)

        self.retranslateUi(MainWindow)

        self.stack.setCurrentIndex(2)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.title1.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p align=\"center\"><span style=\" font-size:44pt; font-weight:700; color:#009de0;\">Collision Study Dynamics</span></p></body></html>", None))
        self.subtitle1.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p align=\"center\"><span style=\" font-size:20pt; color:#000000;\">Computer Vision App with Python</span></p></body></html>", None))
        self.btnStart.setText(QCoreApplication.translate("MainWindow", u"START", None))
        self.instructions.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-size:16pt;\">Pr\u00e9-Ensaio: </span></p><p><span style=\" font-size:16pt;\">---&gt; Ler o guia;</span></p><p><span style=\" font-size:16pt;\">---&gt; Massa dos discos;</span></p><p><span style=\" font-size:16pt;\">---&gt; Raio dos discos;</span></p><p><span style=\" font-size:16pt;\"><br/></span></p><p><span style=\" font-size:16pt;\">Ensaio: </span></p><p><span style=\" font-size:16pt;\">---&gt; Deixar 2 segundos depois do in\u00edcio da grava\u00e7\u00e3o;</span></p><p><span style=\" font-size:16pt;\">---&gt; Lan\u00e7ar os discos e verificar se a colis\u00e3o ocorre;<br/>---&gt; N\u00e3o deixar que os discos voltem a entrar na \u00e1rea de grava\u00e7\u00e3o;</span></p><p><span style=\" font-size:16pt;\">---&gt; Verificar a dete\u00e7\u00e3o e repetir se necess\u00e1rio.<br/></span></p></body></html>", None))
        self.btnNext2.setText(QCoreApplication.translate("MainWindow", u"Seguinte", None))
        self.disk_r_g.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Raio Disco Verde (mm):</p></body></html>", None))
        self.group_val.setPlaceholderText(QCoreApplication.translate("MainWindow", u"---> Ex: 01", None))
        self.disk_m_b.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Massa Disco Azul (g): </p></body></html>", None))
        self.disk_m_b_val.setPlaceholderText(QCoreApplication.translate("MainWindow", u"---> Default: 11.8g", None))
        self.group.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>N\u00famero Grupo: </p></body></html>", None))
        self.disk_m_g.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Massa Disco Verde (g): </p></body></html>", None))
        self.disk_r_b.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Raio Disco Azul (mm):</p></body></html>", None))
        self.disk_m_g_val.setPlaceholderText(QCoreApplication.translate("MainWindow", u"---> Default: 11.8g", None))
        self.disk_r_b_val.setPlaceholderText(QCoreApplication.translate("MainWindow", u"---> Default: 40mm", None))
        self.disk_r_g_val.setPlaceholderText(QCoreApplication.translate("MainWindow", u"--> Default: 40mm", None))
        self.validate.setText(QCoreApplication.translate("MainWindow", u"Validar", None))
    # retranslateUi

