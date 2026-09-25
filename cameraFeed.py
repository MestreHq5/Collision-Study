"""
Camera capture for the Live Feed page (Page "Live Feed" in gui.ui / app.py).
No widget code lives here -- this module only knows about cv2 capture/write
and exposes Qt signals for the GUI to connect to, mirroring the
DetectionWorker/PrintTee pattern already used in helper.py for anything that
has to cross from a background QThread onto the GUI thread.
"""

from pathlib import Path
import time

import cv2
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

try:
    from pygrabber.dshow_graph import FilterGraph
except ImportError:
    FilterGraph = None


# Fixed preset dropdowns (Page "Live Feed" settings row) -- deliberately not
# free-form entry, and not queried from the camera itself (OpenCV/DirectShow
# don't expose a reliable "supported modes" list cross-camera). Each list's
# first entry is the default, matching this project's locked deployment spec
# (CLAUDE.md: 1080p@60fps webcam). Whatever the camera actually negotiates is
# measured and used downstream regardless (see CameraWorker.stop_recording)
# -- same "trust measured, not requested" rule the uploaded-file path already
# follows for its own FPS.
RESOLUTION_PRESETS = [(1920, 1080), (1280, 720), (640, 480)]
FPS_PRESETS = [60, 30, 24]


def list_cameras(max_probe=5):
    """
    Returns [(index, name), ...] for every camera DirectShow can open.

    Names come from pygrabber's device enumeration; index i is paired with
    pygrabber's i-th device under the assumption that cv2.VideoCapture(i,
    cv2.CAP_DSHOW) and FilterGraph().get_input_devices()[i] enumerate in the
    same order -- true in practice on Windows (both walk the same DirectShow
    device list) but not a guarantee either API makes explicit, so this falls
    back to a generic "Camera N" label if the name list comes up short or
    pygrabber isn't importable at all.
    """
    names = []
    if FilterGraph is not None:
        try:
            names = FilterGraph().get_input_devices()
        except Exception:
            names = []

    cameras = []
    for i in range(max_probe):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            name = names[i] if i < len(names) else f"Camera {i}"
            cameras.append((i, name))
        cap.release()
    return cameras


def _bgr_to_qimage(frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    # .copy() -- otherwise the QImage aliases `rgb`'s buffer, which goes out
    # of scope (and can be overwritten by the next frame) as soon as this
    # function returns.
    return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()


class CameraWorker(QThread):
    """
    Owns one cv2.VideoCapture for the whole Live Feed page visit: runs a
    continuous preview loop from the moment the page is entered (grabbing
    frames but not writing them) and, between start_recording()/
    stop_recording(), also writes those same frames to disk. Keeping preview
    and recording on one capture loop (rather than two independent ones)
    guarantees the recorded file and the on-screen preview never drift from
    each other's timing.

    start_recording()/stop_recording() are plain methods called directly from
    the GUI thread (button clicks), not routed through a signal -- the only
    state they touch is a couple of flags and a VideoWriter handle, assigned
    in an order (`_writer` before `_recording`) safe for the worker thread's
    read of the same flags, so the extra indirection of a signal/slot round
    trip isn't needed here.

    frame_ready fires for every grabbed frame (preview keeps running for the
    whole page visit, recording or not). recording_finished fires once, after
    stop_recording(), with the *measured* fps (elapsed wall-clock time /
    frames actually written) -- not the requested preset -- since a webcam
    frequently can't sustain the requested rate under real load (CLAUDE.md:
    "Actual webcam fps drifts below the nominal 60 -- use each video's own
    measured fps, not an assumed 60").
    """
    frame_ready = pyqtSignal(QImage)
    recording_finished = pyqtSignal(float, int)  # measured_fps, frame_count
    error = pyqtSignal(str)

    def __init__(self, device_index, width, height, requested_fps, dest_path):
        super().__init__()
        self.device_index = device_index
        self.width = width
        self.height = height
        self.requested_fps = requested_fps
        self.dest_path = Path(dest_path)

        self._running = False
        self._recording = False
        self._writer = None
        self._record_start = None
        self._frames_written = 0

    def start_recording(self):
        self._frames_written = 0
        self._writer = cv2.VideoWriter(
            str(self.dest_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            self.requested_fps,
            (self.width, self.height),
        )
        self._record_start = time.perf_counter()
        self._recording = True

    def stop_recording(self):
        self._recording = False
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        elapsed = max(time.perf_counter() - (self._record_start or 0.0), 1e-6)
        measured_fps = self._frames_written / elapsed if self._frames_written else 0.0
        self.recording_finished.emit(measured_fps, self._frames_written)

    def stop(self):
        """Stops the whole preview/capture loop -- call when leaving the page."""
        self._running = False
        self.wait(2000)

    def run(self):
        cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            self.error.emit(f"Could not open camera {self.device_index}")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.requested_fps)

        self._running = True
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    continue
                if self._recording and self._writer is not None:
                    self._writer.write(frame)
                    self._frames_written += 1
                self.frame_ready.emit(_bgr_to_qimage(frame))
        finally:
            if self._writer is not None:
                self._writer.release()
            cap.release()


class PlaybackWorker(QThread):
    """
    Replays an already-recorded file into the same preview widget the live
    camera used, at the file's own fps -- the "play the take back" control
    shown on top of the video area after Stop. Never active at the same time
    as a CameraWorker (the live camera loop is stopped before this starts).
    """
    frame_ready = pyqtSignal(QImage)
    finished_playback = pyqtSignal()

    def __init__(self, video_path):
        super().__init__()
        self.video_path = Path(video_path)
        self._running = False

    def stop(self):
        self._running = False
        self.wait(2000)

    def run(self):
        cap = cv2.VideoCapture(str(self.video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        delay = 1.0 / fps
        self._running = True
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    break
                self.frame_ready.emit(_bgr_to_qimage(frame))
                time.sleep(delay)
        finally:
            cap.release()
            self._running = False
            self.finished_playback.emit()
