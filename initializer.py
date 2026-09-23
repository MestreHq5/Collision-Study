import sys
from pathlib import Path
from dotenv import load_dotenv

# Looked up next to the .exe when frozen (sys.executable), not sys._MEIPASS
# -- that's PyInstaller's bundled/internal folder, not somewhere a user
# would edit a config file. In dev, that's just this file's own directory.
# Must run before `import app` -- app.py's import chain (Post_process ->
# notifier) reads NTFY_TOPIC from os.environ at module load time, so any
# .env values need to already be in the environment by then.
_env_base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
load_dotenv(_env_base / ".env")

import app

# Initialize Everything Starting on the GUI
# Application Entry Point
if __name__ == "__main__":
    app.main()