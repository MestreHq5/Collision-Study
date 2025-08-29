import cv2
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap

class WebcamSimple:
    def __init__(self, video_label, out_path: Path, cam_index=0):
        self.label = video_label        # QLabel in GUI
        self.out_path = Path(out_path)  # where to save video
        self.cam_index = cam_index
        self.cap = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._update)
        self.recording = False
        self.writer = None

    def start(self):
        # open webcam
        self.cap = cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW)

        # try resolutions in order
        tried = [(1920, 1080, 60), (1280, 720, 60), (1920, 1080, 30)]
        for w, h, fps in tried:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            self.cap.set(cv2.CAP_PROP_FPS,          fps)
            # read back what we got
            rw = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            rh = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            rfps = int(self.cap.get(cv2.CAP_PROP_FPS))
            if rw == w and rh == h and rfps in (fps, fps-1, fps+1):
                print(f"Using {rw}x{rh} @ {rfps}fps")
                break

        self.timer.start(int(1000 / 30))  # ~30 updates/s for GUI preview

    def start_record(self):
        if not self.cap or not self.cap.isOpened():
            return
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.writer = cv2.VideoWriter(str(self.out_path), fourcc, fps, (w, h))
        self.recording = True
        print("Recording started")

    def stop_record(self):
        self.recording = False
        if self.writer:
            self.writer.release()
            self.writer = None
            print("Recording saved:", self.out_path)
            return True
        return False

    def close(self):
        self.timer.stop()
        if self.writer: self.writer.release()
        if self.cap: self.cap.release()

    def _update(self):
        if not self.cap: return
        ret, frame = self.cap.read()
        if not ret: return

        # write frame if recording
        if self.recording and self.writer:
            self.writer.write(frame)

        # show in QLabel
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        self.label.setPixmap(pix.scaled(self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
