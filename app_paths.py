"""
Runtime paths shared by the CLI and desktop app.
"""
import sys
from pathlib import Path


APP_SUPPORT_DIR_NAME = "ZIA Backup Restore"


def app_dir() -> Path:
    """Return the directory where user data should be stored."""
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_SUPPORT_DIR_NAME
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = app_dir()
APP_DIR.mkdir(parents=True, exist_ok=True)
