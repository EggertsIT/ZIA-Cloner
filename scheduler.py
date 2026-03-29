"""
scheduler.py — Set up or remove scheduled sync via cron (macOS/Linux).
"""
import subprocess
import sys
from pathlib import Path

import ui

SCRIPT = Path(__file__).resolve().parent / "sync.py"
PYTHON = sys.executable


def _get_crontab() -> str:
    """Return the current user's crontab as a string, or '' if none exists or cron is unavailable."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else ""
    except FileNotFoundError:
        return ""


def _set_crontab(content: str):
    """Write content as the new crontab by piping it to 'crontab -'.

    Returns True if the crontab was updated successfully, False otherwise.
    """
    proc = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True)
    return proc.returncode == 0


CRON_MARKER = "# ZIA-SYNC-AUTO"

SCHEDULES = {
    "1":  ("Every hour",          "0 * * * *"),
    "2":  ("Every 6 hours",       "0 */6 * * *"),
    "3":  ("Every 12 hours",      "0 */12 * * *"),
    "4":  ("Once a day (2 AM)",   "0 2 * * *"),
    "5":  ("Once a week (Mon 2AM)","0 2 * * 1"),
    "6":  ("Custom",              None),
}


def setup_schedule():
    """Interactively configure a cron job to run 'sync.py --auto' on a schedule.

    Presents the user with preset options (hourly through weekly) plus a custom
    expression option. Removes any existing ZIA sync cron entry (identified by
    CRON_MARKER) before adding the new one. Output is appended to
    backups/logs/sync.log so automated runs leave a trace.

    Returns True if the cron job was installed successfully, False otherwise.
    """
    ui.section("Schedule Automatic Sync")
    print()

    for key, (label, expr) in SCHEDULES.items():
        cron_str = expr if expr else "custom"
        print(f"  {ui._c(ui.DIM, key+'.')} {label:<30} {ui._c(ui.DIM, cron_str)}")

    choice = ui.ask("Choose schedule", default="4")
    if choice not in SCHEDULES:
        ui.error("Invalid choice.")
        return False

    label, cron_expr = SCHEDULES[choice]
    if cron_expr is None:
        cron_expr = ui.ask("Enter cron expression (e.g. '0 3 * * *' = daily at 3am)")
        if not cron_expr:
            return False

    log_dir = SCRIPT.parent / "backups" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "sync.log"

    cron_line = f"{cron_expr} {PYTHON} {SCRIPT} --auto >> {log_file} 2>&1  {CRON_MARKER}"

    current = _get_crontab()
    # Remove existing ZIA sync entries
    lines = [l for l in current.splitlines() if CRON_MARKER not in l]
    lines.append(cron_line)
    new_crontab = "\n".join(lines) + "\n"

    if _set_crontab(new_crontab):
        ui.ok(f"Cron job set: {label}")
        ui.info(f"Expression: {cron_expr}")
        ui.info(f"Log: {log_file}")
        return True
    else:
        ui.error("Failed to set crontab. Try running: crontab -e manually.")
        print(f"\n  Add this line:\n  {ui._c(ui.CYN, cron_line)}")
        return False


def remove_schedule():
    """Remove any existing ZIA sync cron job from the user's crontab.

    Identifies ZIA sync entries by the presence of CRON_MARKER in the line.
    Prints a warning if no entry is found.
    """
    current = _get_crontab()
    if CRON_MARKER not in current:
        ui.warn("No ZIA sync schedule found.")
        return
    lines = [l for l in current.splitlines() if CRON_MARKER not in l]
    _set_crontab("\n".join(lines) + "\n")
    ui.ok("Scheduled sync removed.")


def show_schedule():
    """Print the currently active ZIA sync cron schedule, or a hint to set one up."""
    current = _get_crontab()
    lines = [l for l in current.splitlines() if CRON_MARKER in l]
    if not lines:
        ui.warn("No automatic sync scheduled.")
        print(f"  Run: {ui._c(ui.CYN, 'python3 sync.py schedule')} to set one up.")
    else:
        ui.ok("Active schedule:")
        for l in lines:
            print(f"  {ui._c(ui.CYN, l.replace(CRON_MARKER, '').strip())}")
