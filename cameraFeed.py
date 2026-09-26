"""
Camera capture for the Live Feed page (Page "Live Feed" in gui.ui / app.py).
No widget code lives here -- this module only knows about cv2 capture/write
and exposes Qt signals for the GUI to connect to, mirroring the
DetectionWorker/PrintTee pattern already used in helper.py for anything that
has to cross from a background QThread onto the GUI thread.
"""

from collections import deque
from pathlib import Path
import os
import queue
import threading
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
# measured and used downstream regardless (see CameraWorker) -- same "trust
# measured, not requested" rule the uploaded-file path already follows.
RESOLUTION_PRESETS = [(1920, 1080), (1280, 720), (640, 480)]
FPS_PRESETS = [60, 30, 24]

# Preview only -- the recorded file always gets every frame at full size.
# Emitting every 1080p60 frame to the GUI thread (RGB convert + QImage copy +
# rescale there) can't keep up and just queues signals, so the preview is
# downscaled in the worker and rate-capped.
PREVIEW_MAX_WIDTH = 1280
PREVIEW_MAX_HZ = 30.0

# Consecutive failed reads (seconds) before the device is declared lost --
# e.g. the external USB camera was unplugged mid-session.
READ_FAILURE_TIMEOUT_S = 2.0

# If the container fps written at record time (the live preview's measured
# rate) differs from the rate actually measured over the recording by more
# than this, the file is rewritten with the measured rate. detector.main()
# trusts the container's fps for dt, so a wrong header scales every
# velocity by the same error.
FPS_HEADER_TOLERANCE = 0.01

# QThreads whose stop() timed out -- kept referenced so Python doesn't
# garbage-collect a still-running QThread (which aborts the process with
# "QThread: Destroyed while thread is still running").
_ORPHANS = []


def list_cameras(max_probe=5):
    """
    Returns [(index, name), ...] for every camera DirectShow can open.

    Names come from pygrabber's device enumeration; index i is paired with
    pygrabber's i-th device under the assumption that cv2.VideoCapture(i,
    cv2.CAP_DSHOW) and FilterGraph().get_input_devices()[i] enumerate in the
    same order -- true in practice on Windows (both walk the same DirectShow
    device list) but not a guarantee either API makes explicit, so this falls
    back to a generic "Camera N" label if the name list comes up short or
    pygrabber isn't importable at all. Listed-but-unopenable devices (e.g.
    "OBS Virtual Camera" while OBS isn't running) are skipped.

    Must not be called while this app's own CameraWorker holds a device --
    DirectShow lets only one client open a UVC camera, so the held device
    would probe as missing.
    """
    names = []
    if FilterGraph is not None:
        try:
            names = FilterGraph().get_input_devices()
        except Exception:
            names = []

    cameras = []
    for i in range(max(max_probe, len(names))):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            name = names[i] if i < len(names) else f"Camera {i}"
            cameras.append((i, name))
        cap.release()
    return cameras


def _stop_qthread(thread, timeout_ms=5000):
    if not thread.wait(timeout_ms):
        print(f"[WARN] {type(thread).__name__} did not stop within "
              f"{timeout_ms / 1000:.0f}s; leaving it to finish in the background.")
        _ORPHANS.append(thread)


def _bgr_to_qimage(frame):
    h, w = frame.shape[:2]
    if w > PREVIEW_MAX_WIDTH:
        scale = PREVIEW_MAX_WIDTH / w
        frame = cv2.resize(frame, (PREVIEW_MAX_WIDTH, round(h * scale)),
                           interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    # .copy() -- otherwise the QImage aliases `rgb`'s buffer, which goes out
    # of scope (and can be overwritten by the next frame) as soon as this
    # function returns.
    return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()


def _rewrite_with_fps(src, dst, fps):
    """Re-encodes src into dst with a corrected container fps."""
    cap = cv2.VideoCapture(str(src))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            out.write(frame)
    finally:
        cap.release()
        out.release()


class _FrameWriter:
    """
    Encodes on its own thread so a 1080p60 capture loop isn't throttled by
    mp4v encode time (~14 ms/frame measured at 1080p on the dev laptop,
    against a 16.7 ms frame budget at 60 fps). cv2 releases the GIL while
    encoding, so a plain threading.Thread is enough. The queue is unbounded
    on purpose: dropping frames under backpressure would silently corrupt
    the timing, while a short collision clip's backlog just drains at stop.
    """

    def __init__(self, path, fps, size):
        self.path = Path(path)
        self._writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        if not self._writer.isOpened():
            raise RuntimeError(f"Could not open video writer at {self.path}")
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="FrameWriter", daemon=True)
        self._thread.start()

    def write(self, frame):
        self._queue.put(frame)

    def close(self):
        self._queue.put(None)
        self._thread.join()
        self._writer.release()

    def _run(self):
        while True:
            frame = self._queue.get()
            if frame is None:
                return
            self._writer.write(frame)


class CameraWorker(QThread):
    """
    Owns one cv2.VideoCapture for the whole Live Feed page visit: runs a
    continuous preview loop from the moment the page is entered and, between
    start_recording()/stop_recording(), also writes those same frames to
    disk. Keeping preview and recording on one capture loop (rather than two
    independent ones) guarantees the recorded file and the on-screen preview
    never drift from each other's timing.

    start_recording()/stop_recording() are called from the GUI thread but
    only set request flags; the capture thread itself opens and closes the
    writer on its next frame. That way the writer is created with the frame
    size the camera *actually* delivers (a 1080p request on a 720p camera
    silently gets 720p, and cv2.VideoWriter silently drops frames of the
    wrong size) and the container fps is the live measured rate, and no
    writer handle is ever touched from two threads.

    Signals:
      frame_ready        -- downscaled, rate-capped preview frames.
      stats              -- (width, height, measured_fps) about once a second.
      recording_saving   -- recording stopped, file being finalized.
      recording_finished -- (measured_fps, frame_count, width, height), once the
                            file on disk is final. measured_fps comes from the
                            recorded frames' own timestamps, not the requested
                            preset (CLAUDE.md: webcam fps drifts below nominal).
      error              -- device couldn't be opened, or was lost mid-session.
    """
    frame_ready = pyqtSignal(QImage)
    stats = pyqtSignal(int, int, float)
    recording_saving = pyqtSignal()
    recording_finished = pyqtSignal(float, int, int, int)
    error = pyqtSignal(str)

    def __init__(self, device_index, width, height, requested_fps, dest_path):
        super().__init__()
        self.device_index = device_index
        self.width = width
        self.height = height
        self.requested_fps = requested_fps
        self.dest_path = Path(dest_path)

        # True from construction, not from inside run(): opening a DirectShow
        # device takes ~0.4-1.5 s, and a stop() issued during that window
        # (settings changed, page left) must still be honored once the open
        # returns -- otherwise run() would set this True afterwards and keep
        # the device locked indefinitely.
        self._running = True
        self._record_requested = False
        self._stop_requested = False
        self.is_recording = False

    def start_recording(self):
        self._stop_requested = False
        self._record_requested = True

    def stop_recording(self):
        self._record_requested = False
        self._stop_requested = True

    def stop(self):
        """Stops the whole preview/capture loop -- call when leaving the page.
        Blocks until the device is actually released."""
        self._running = False
        _stop_qthread(self)

    def _open(self):
        cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            return None
        # Order matters on DirectShow: size, then fps, then MJPG *last*.
        # Measured on the dev laptop's webcam at 1280x720: MJPG set last ->
        # MJPG @ 30 fps; MJPG set first, or not at all -> YUY2 @ 10 fps.
        # Uncompressed YUY2 can't carry 1080p60 over USB 2.0 at all, so for
        # the deployment spec MJPG isn't optional.
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.requested_fps)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        return cap

    def run(self):
        cap = self._open()
        if cap is None:
            if self._running:
                self.error.emit(f"Could not open camera {self.device_index} "
                                f"(is another application using it?)")
            return

        timestamps = deque(maxlen=90)   # rolling window for the live fps estimate
        last_stats = 0.0
        last_preview = 0.0
        fail_since = None

        writer = None
        tmp_path = self.dest_path.with_name(self.dest_path.stem + "_tmp" + self.dest_path.suffix)
        header_fps = None
        rec_first = rec_last = None
        rec_count = 0
        frame_size = None

        def finish_recording():
            nonlocal writer
            self.is_recording = False
            self.recording_saving.emit()
            writer.close()
            writer = None
            measured = (rec_count - 1) / (rec_last - rec_first) if rec_count > 1 and rec_last > rec_first else 0.0
            try:
                if measured > 0 and abs(header_fps - measured) / measured > FPS_HEADER_TOLERANCE:
                    _rewrite_with_fps(tmp_path, self.dest_path, measured)
                    os.remove(tmp_path)
                else:
                    os.replace(tmp_path, self.dest_path)
            except OSError as e:
                self.error.emit(f"Could not save recording: {e}")
                return
            w, h = frame_size
            self.recording_finished.emit(measured, rec_count, w, h)

        try:
            while self._running:
                ok, frame = cap.read()
                now = time.perf_counter()
                if not ok:
                    fail_since = fail_since or now
                    if now - fail_since > READ_FAILURE_TIMEOUT_S:
                        self.error.emit("Camera stopped delivering frames (disconnected?)")
                        break
                    time.sleep(0.01)
                    continue
                fail_since = None
                timestamps.append(now)
                frame_size = (frame.shape[1], frame.shape[0])
                live_fps = ((len(timestamps) - 1) / (timestamps[-1] - timestamps[0])
                            if len(timestamps) > 1 else 0.0)

                if self._record_requested and writer is None:
                    self._record_requested = False
                    # Preview has usually run for seconds by now, so the
                    # rolling estimate is already within a fraction of a
                    # percent; the requested preset is only a fallback.
                    header_fps = live_fps if len(timestamps) >= 30 else float(self.requested_fps)
                    try:
                        writer = _FrameWriter(tmp_path, header_fps, frame_size)
                    except RuntimeError as e:
                        self.error.emit(str(e))
                    else:
                        rec_first, rec_count = now, 0
                        self.is_recording = True

                if writer is not None:
                    if self._stop_requested:
                        self._stop_requested = False
                        finish_recording()
                    else:
                        writer.write(frame)
                        rec_last = now
                        rec_count += 1

                # 0.8x slack: frame arrival jitters by a few ms, and a strict
                # 1/30 s gate against a ~30 fps camera skips every early frame.
                if now - last_preview >= 0.8 / PREVIEW_MAX_HZ:
                    last_preview = now
                    self.frame_ready.emit(_bgr_to_qimage(frame))
                if now - last_stats >= 1.0:
                    last_stats = now
                    self.stats.emit(frame_size[0], frame_size[1], live_fps)
        finally:
            # Leaving the page (or losing the device) mid-take still produces
            # a finished, correctly-timed file rather than a truncated one.
            if writer is not None:
                finish_recording()
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
        self._running = True  # see CameraWorker.__init__

    def stop(self):
        self._running = False
        _stop_qthread(self)

    def run(self):
        cap = cv2.VideoCapture(str(self.video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        delay = 1.0 / fps
        next_t = time.perf_counter()
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    break
                self.frame_ready.emit(_bgr_to_qimage(frame))
                # Schedule against a running clock rather than sleeping a
                # fixed delay, so decode/convert time doesn't slow playback.
                next_t += delay
                time.sleep(max(0.0, next_t - time.perf_counter()))
        finally:
            cap.release()
            self._running = False
            self.finished_playback.emit()
