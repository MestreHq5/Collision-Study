# Collision-Study Instructions

This file contains architectural mandates, conventions, and workflows for the Collision-Study project.

## Tech Stack
- **Language:** Python 3.x
- **GUI Framework:** PyQt6 (using `.ui` files via `uic`)
- **Computer Vision:** OpenCV (`cv2`)
- **Threading:** `QThread` for non-blocking camera operations
- **Packaging:** PyInstaller

## Architecture & Conventions

### Video Source Selection
- After validating group and disk parameters, the application prompts the user to choose between **Live Record** (using the camera) or **Submit Existing** (uploading a video file).
- If **Submit Existing** is chosen:
  - The selected video is copied to the workspace as `Recording.mp4`.
  - The FPS is automatically extracted from the video file using OpenCV.
  - The application skips directly to the Analysis/Processing page.

### Resource Handling
- Always use the `resource_path` helper (found in `app.py`) to access bundled files (UI, images, etc.). This ensures compatibility between development and frozen (PyInstaller) environments.
- UI files should be loaded via `uic.loadUi(resource_path('gui.ui'), self)`.

### Camera & Video Operations
- Camera operations are handled in `CameraWorker` (inheriting from `QThread`).
- UI updates from background threads must use `pyqtSignal`.
- OpenCV logging is suppressed by default (`OPENCV_LOG_LEVEL=SILENT`).

### Performance
- The application attempts to configure cameras for high frame rates (e.g., 1920x1080 @ 60fps).

## Known Issues & Troubleshooting

### OpenCV Video Writing
- There is a known intermittent "Unknown C++ exception from OpenCV code" during recording (`self._writer.write(frame_bgr)`).
- "Invalid pts" errors have been observed with the `mpeg4` encoder.
- Check `Notes.txt` for specific traceback details.

## Workflow & Build

### Development
- Main entry point: `app.py` or `initializer.py`.

### Building the Executable
- Use the following PyInstaller command (as seen in `Notes.txt`):
  ```powershell
  pyinstaller `
    --name CollisionStudy `
    --onedir `
    --noconfirm `
    --clean `
    --console `
    --collect-all PyQt6 `
    --collect-binaries cv2 `
    --add-data "gui.ui;." `
    --add-data "Images;Images" `
    initializer.py
  ```
