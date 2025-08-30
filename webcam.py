
# webcam.py
# Robust webcam preview + recording module for PySide6 + OpenCV (Windows-optimized, DirectShow)
#
# Features
# - Live preview to a QLabel via Qt signals (no GUI blocking)
# - Start/stop recording to AVI (MJPG preferred, XVID fallback)
# - Resolution/FPS negotiation with priority:
#     1280x720 @ 60  -> 1920x1080 @ 60 -> 1280x720 @ 30 -> 1920x1080 @ 30
# - Uses DirectShow backend on Windows for reliability
# - Cleans up camera, writer, and thread on stop/close
#
# Usage (as already wired in your project):
#   self.cam = WebcamSimple(self.videoLabel, "path/to/Recording.avi")
#   self.cam.start()            # start preview
#   self.cam.start_record()     # start recording
#   self.cam.stop_record()      # stop recording
#   self.cam.close()            # release resources
#
# Notes:
# - Many webcams only deliver 60 fps at 1280x720 with MJPG. We explicitly request MJPG from the camera.
# - If your camera cannot do 60 fps, the module gracefully falls back to 30 fps.
# - For best results, record to an SSD and avoid heavy CPU tasks while recording.

from __future__ import annotations
import sys
import os
import time
import threading
from dataclasses import dataclass
from typing import Optional, Tuple, List

import cv2
import numpy as np

from PySide6.QtCore import QObject, QThread, Signal, Qt, QSize
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel


# ------------------------------
# Utility
# ------------------------------

@dataclass
class CameraMode:
    width: int
    height: int
    fps: int


PREFERRED_MODES: List[CameraMode] = [
    CameraMode(1280, 720, 60),
    CameraMode(1920, 1080, 60),
    CameraMode(1280, 720, 30),
    CameraMode(1920, 1080, 30),
]


def _platform_uses_directshow() -> bool:
    # Use DirectShow on Windows
    return sys.platform.startswith("win")


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


# ------------------------------
# QThread worker
# ------------------------------

class CameraWorker(QThread):
    frame_ready = Signal(QImage)             # emitted for live preview
    status_text = Signal(str)                # optional status/debug messages
    recording_state_changed = Signal(bool)   # True when recording starts, False when stops

    def __init__(self, device_index: int = 0, preferred_modes: List[CameraMode] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.device_index = device_index
        self.preferred_modes = preferred_modes or PREFERRED_MODES
        self.cap: Optional[cv2.VideoCapture] = None
        self.writer: Optional[cv2.VideoWriter] = None

        self.target_mode: Optional[CameraMode] = None
        self.actual_size: Tuple[int, int] = (0, 0)  # (w, h)
        self.actual_fps: float = 0.0

        self._running = threading.Event()
        self._running.clear()

        self._recording = threading.Event()
        self._recording.clear()

        self._frames_written = 0

    # --------------- Public control ---------------

    def stop(self) -> None:
        """Stop capture thread and release resources."""
        self._running.clear()
        self.wait(1000)  # allow run() to exit
        self._cleanup()

    def start_recording(self, path: str, codec_priority: Tuple[str, ...] = ("MJPG", "XVID")) -> None:
        """Start writing frames to an AVI file with the given codec priority."""
        if not self.cap or not self.cap.isOpened():
            self.status_text.emit("Camera not started; cannot record.")
            return

        # Ensure writer dir exists
        _ensure_parent_dir(path)

        # Close previous writer if any
        if self.writer is not None:
            try:
                self.writer.release()
            except Exception:
                pass
            self.writer = None

        # Determine size and fps for writer (use actual camera output)
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self._safe_fps_for_writer()

        # Try codecs in order
        opened = False
        for fourcc_name in codec_priority:
            fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
            writer = cv2.VideoWriter(path, fourcc, fps, (w, h), True)
            if writer.isOpened():
                self.writer = writer
                opened = True
                self.status_text.emit(f"Recording to {path} with codec={fourcc_name}, {w}x{h}@{fps:.2f}fps")
                break

        if not opened:
            self.status_text.emit("Failed to open VideoWriter. Check path/permissions and installed codecs.")
            return

        self._frames_written = 0
        self._recording.set()
        self.recording_state_changed.emit(True)

    def stop_recording(self) -> Tuple[int, float]:
        """Stop writing and return (frames_written, approx_duration_sec)."""
        self._recording.clear()
        self.recording_state_changed.emit(False)
        if self.writer is not None:
            try:
                self.writer.release()
            finally:
                self.writer = None
        # Return stats
        duration = getattr(self, "_record_start_time", None)
        if duration is not None:
            duration = time.perf_counter() - duration
        else:
            duration = 0.0
        return self._frames_written, duration

    def is_recording(self) -> bool:
        return self._recording.is_set()

    # --------------- Thread main ---------------

    def run(self) -> None:
        self._running.set()
        try:
            self._open_camera_and_negotiate()
            if not self.cap or not self.cap.isOpened():
                self.status_text.emit("Failed to open camera.")
                return

            last_fps_tick = time.perf_counter()
            frames_since_tick = 0
            self._record_start_time = None

            while self._running.is_set():
                ok, frame_bgr = self.cap.read()
                if not ok:
                    # transient read error; short sleep to avoid spin
                    time.sleep(0.002)
                    continue

                # Preview: convert to QImage (RGB888)
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                h, w, _ = frame_rgb.shape
                bytes_per_line = 3 * w
                # .copy() ensures memory remains valid after function returns
                qimg = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
                self.frame_ready.emit(qimg)

                # Recording (do it in the same thread as capture to avoid bottlenecks)
                if self._recording.is_set() and self.writer is not None:
                    if self._record_start_time is None:
                        self._record_start_time = time.perf_counter()
                    try:
                        self.writer.write(frame_bgr)
                        self._frames_written += 1
                    except Exception as e:
                        self.status_text.emit(f"VideoWriter error: {e}")
                        # Attempt to stop recording to prevent further issues
                        self.stop_recording()

                # Basic FPS measurement (preview rate)
                frames_since_tick += 1
                now = time.perf_counter()
                if now - last_fps_tick >= 1.0:
                    self.actual_fps = frames_since_tick / (now - last_fps_tick)
                    frames_since_tick = 0
                    last_fps_tick = now
        finally:
            self._cleanup()

    # --------------- Internal helpers ---------------

    def _cleanup(self) -> None:
        # Release writer first
        if self.writer is not None:
            try:
                self.writer.release()
            except Exception:
                pass
            self.writer = None

        # Release camera
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _open_camera_and_negotiate(self) -> None:
        # Choose backend
        backend = cv2.CAP_DSHOW if _platform_uses_directshow() else 0

        # Open capture
        cap = cv2.VideoCapture(self.device_index, backend)
        if not cap or not cap.isOpened():
            self.status_text.emit("OpenCV could not open the webcam.")
            self.cap = None
            return

        # Reduce buffer to minimize latency (not supported on all backends)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # Request MJPG from the CAMERA (important for 60 fps on many webcams)
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            pass

        # Try preferred modes in order
        selected = None
        for mode in self.preferred_modes:
            self._try_set_mode(cap, mode)
            got_size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
            got_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0

            # Some drivers return 0 for FPS; accept and verify by sampling later
            # For selection we consider width/height matching and fps close enough if > (mode.fps - 5)
            if got_size == (mode.width, mode.height) and (got_fps == 0.0 or got_fps >= mode.fps - 5):
                selected = mode
                break

        # If none matched, just keep whatever the camera selected
        if selected is None:
            selected = CameraMode(int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                  int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                                  int(cap.get(cv2.CAP_PROP_FPS) or 30))

        self.target_mode = selected
        self.actual_size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.actual_fps = cap.get(cv2.CAP_PROP_FPS) or float(selected.fps)

        self.cap = cap
        self.status_text.emit(f"Camera opened: requested {selected.width}x{selected.height}@{selected.fps} "
                              f"-> got {self.actual_size[0]}x{self.actual_size[1]}@{self.actual_fps:.2f} (MJPG)")

    def _try_set_mode(self, cap: cv2.VideoCapture, mode: CameraMode) -> None:
        # Order matters: set FPS after size for DirectShow
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, mode.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, mode.height)
        cap.set(cv2.CAP_PROP_FPS, mode.fps)

    def _safe_fps_for_writer(self) -> float:
        """Select a sane FPS for the writer (fallback if camera reports 0)."""
        fps = self.cap.get(cv2.CAP_PROP_FPS) if self.cap else 0.0
        if not fps or fps <= 1.0:
            # fallback to target or at least 30
            if self.target_mode:
                return float(self.target_mode.fps)
            return 30.0
        return float(fps)


# ------------------------------
# Public facade integrated with PySide6 QLabel
# ------------------------------

class WebcamSimple(QObject):
    """
    Facade used by the existing app. Manages a CameraWorker thread and updates a QLabel.
    """
    def __init__(self, label: QLabel, out_path: str, device_index: int = 0, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.label = label
        self.out_path = str(out_path)
        self.device_index = device_index

        self.worker: Optional[CameraWorker] = None
        self.recording: bool = False

        # When label is resized, we want smooth scaling
        if hasattr(self.label, "setScaledContents"):
            self.label.setScaledContents(False)  # we'll scale via QPixmap for aspect ratio

    # ---- Lifecycle ----
    def start(self) -> None:
        if self.worker is not None:
            return
        self.worker = CameraWorker(self.device_index)
        self.worker.frame_ready.connect(self._on_frame_ready, Qt.ConnectionType.QueuedConnection)
        self.worker.status_text.connect(self._on_status)
        self.worker.recording_state_changed.connect(self._on_recording_state_changed)
        self.worker.start()  # QThread.start()

    def start_record(self) -> None:
        if not self.worker:
            return
        self.worker.start_recording(self.out_path, codec_priority=("MJPG", "XVID"))
        self.recording = self.worker.is_recording()

    def stop_record(self) -> None:
        if not self.worker:
            return
        frames, duration = self.worker.stop_recording()
        self.recording = False
        # Optional: print basic recording stats
        if duration > 0:
            approx_fps = frames / duration
            print(f"[WebcamSimple] Recording stopped. Frames={frames}, Duration={duration:.2f}s, ~FPS={approx_fps:.2f}")
        else:
            print("[WebcamSimple] Recording stopped. No duration measured.")

    def close(self) -> None:
        if self.worker is not None:
            try:
                if self.recording:
                    self.stop_record()
                self.worker.stop()
            finally:
                self.worker = None

    # ---- Slots ----
    def _on_frame_ready(self, qimg: QImage) -> None:
        # Scale to label while keeping aspect ratio
        if self.label is None:
            return
        if self.label.width() <= 0 or self.label.height() <= 0:
            pix = QPixmap.fromImage(qimg)
        else:
            pix = QPixmap.fromImage(qimg).scaled(
                self.label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        self.label.setPixmap(pix)

    def _on_status(self, msg: str) -> None:
        # Print to console; could also surface in the GUI if desired
        print(f"[Camera] {msg}")

    def _on_recording_state_changed(self, is_rec: bool) -> None:
        self.recording = is_rec
        state = "ON" if is_rec else "OFF"
        print(f"[Camera] Recording {state}")