#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║           ZIA Sync — Tenant Migration & Sync Tool       ║
╚══════════════════════════════════════════════════════════╝

Usage (as a complete beginner):

    python3 sync.py              # guided sync (asks before applying)
    python3 sync.py --auto       # fully automatic, no prompts (for cron)
    python3 sync.py setup        # re-configure tenants
    python3 sync.py backup       # backup only (no sync)
    python3 sync.py report       # open latest report in browser
    python3 sync.py schedule     # set up automatic sync
    python3 sync.py dry-run      # show what WOULD change, don't apply
"""

import sys
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ── Dependency check ──────────────────────────────────────────────────────────
try:
    import ui
except ImportError:
    print("ERROR: Missing ui.py — run this from the zia-migration directory.")
    sys.exit(1)

import ui
from config_manager import load as load_config, is_configured, setup_wizard, CONFIG_PATH
from zia_client import ZIAClient
from engine import backup_tenant, compute_diff, has_changes, print_diff_summary, apply_diff
from report_gen import gen_report
from resources import MIGRATION_ORDER

BACKUPS_DIR = Path(__file__).parent / "backups"
BACKUP_A    = BACKUPS_DIR / "tenant_a.json"
BACKUP_B    = BACKUPS_DIR / "tenant_b.json"
DIFF_FILE   = BACKUPS_DIR / "diff.json"
REPORT_FILE = BACKUPS_DIR / "report.html"
LOGS_DIR    = BACKUPS_DIR / "logs"


def make_client(tenant_cfg: dict) -> ZIAClient:
    """Construct a ZIAClient from a tenant config dict (as stored in config.json)."""
    return ZIAClient(
        tenant_cfg["cloud"],
        tenant_cfg["username"],
        tenant_cfg["password"],
        tenant_cfg["api_key"],
    )


def open_report(path: Path):
    """Open an HTML file in the default browser using the platform's native command.

    Supports macOS (open), Linux (xdg-open), and Windows (start).
    Failures are silently ignored so a missing browser never crashes the tool.
    """
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)])
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", str(path)])
        elif sys.platform == "win32":
            subprocess.run(["start", str(path)], shell=True)
    except Exception:
        pass


def save_log(content: dict):
    """Append a timestamped JSON log file to backups/logs/.

    Each sync run produces one log file named sync_YYYYMMDD_HHMMSS.json containing
    the diff summary and the full apply result (all operations, errors, etc.).

    Returns the Path of the written log file.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"sync_{ts}.json"
    log_path.write_text(json.dumps(content, indent=2))
    return log_path


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_setup(reconfigure=True):
    """Launch the interactive setup wizard to configure or reconfigure tenant credentials."""
    setup_wizard(reconfigure=reconfigure)


def cmd_backup(cfg: dict, which: str = "both"):
    """Authenticate, back up, and log out for one or both tenants.

    Downloads all resources from the specified tenant(s) and writes the results
    to BACKUP_A and/or BACKUP_B in the backups/ directory. Always logs out in a
    finally block to avoid leaving open sessions even if the backup fails.

    Args:
        cfg:   Full config dict from config.json.
        which: 'a' for source only, 'b' for target only, 'both' for both (default).
    """
    if which in ("a", "both"):
        client_a = make_client(cfg["tenant_a"])
        try:
            client_a.authenticate()
            backup_tenant(client_a, cfg["tenant_a"]["label"], BACKUP_A)
        finally:
            client_a.logout()

    if which in ("b", "both"):
        client_b = make_client(cfg["tenant_b"])
        try:
            client_b.authenticate()
            backup_tenant(client_b, cfg["tenant_b"]["label"], BACKUP_B)
        finally:
            client_b.logout()


def cmd_dry_run(cfg: dict):
    """Back up both tenants, compute the diff, simulate all operations, and open a report.

    Runs the full pipeline (backup → diff → apply with dry_run=True) but never
    modifies the target tenant. The simulated operations are recorded in the report
    so the user can review exactly what would happen before committing.
    """
    ui.header("ZIA Sync — Dry Run")

    cmd_backup(cfg, "both")

    src = json.loads(BACKUP_A.read_text())
    tgt = json.loads(BACKUP_B.read_text()) if BACKUP_B.exists() else {"meta": {}, "resources": {}}
    diff = compute_diff(src, tgt)
    DIFF_FILE.write_text(json.dumps(diff, indent=2))

    if not has_changes(diff):
        ui.ok("Tenants are already in sync!")
        return

    print_diff_summary(diff)

    ui.section("Dry-run simulation")
    client_b = make_client(cfg["tenant_b"])
    try:
        client_b.authenticate()
        result = apply_diff(client_b, diff, src,
                            dry_run=True,
                            no_delete=cfg["sync"].get("no_delete", False),
                            sync_sensitive=cfg["sync"].get("sync_sensitive", False))
    finally:
        client_b.logout()

    report_path = gen_report(diff, src, result, REPORT_FILE)
    ui.ok(f"Report → {report_path}")
    open_report(report_path)


def cmd_sync(cfg: dict, auto: bool = False):
    """Run the full sync pipeline: backup → diff → confirm → apply → activate → report.

    Steps:
      1. Back up both tenants.
      2. Compute the diff.
      3. If there are no changes, generate a report and exit early.
      4. Show the diff summary. In interactive mode, ask for confirmation.
      5. Apply all changes to the target tenant.
      6. Activate the changes (if auto_activate is enabled in config).
      7. Save a JSON log and generate/open the HTML report.

    Args:
        cfg:  Full config dict from config.json.
        auto: If True, skip the confirmation prompt (used by cron / --auto flag).
    """
    ui.header("ZIA Sync")
    print(f"\n  {ui._c(ui.DIM, 'Source:')} {cfg['tenant_a']['label']} "
          f"{ui._c(ui.DIM, '→')} "
          f"{ui._c(ui.DIM, 'Target:')} {cfg['tenant_b']['label']}\n")

    # ── Step 1: Backup ──────────────────────────────────────────────────────
    cmd_backup(cfg, "both")

    # ── Step 2: Diff ────────────────────────────────────────────────────────
    src = json.loads(BACKUP_A.read_text())
    tgt = json.loads(BACKUP_B.read_text()) if BACKUP_B.exists() else {"meta": {}, "resources": {}}
    diff = compute_diff(src, tgt)
    DIFF_FILE.write_text(json.dumps(diff, indent=2))

    if not has_changes(diff):
        ui.section("Result")
        ui.ok("Tenants are already in sync — nothing to do.")
        report_path = gen_report(diff, src, None, REPORT_FILE)
        ui.ok(f"Report → {report_path}")
        if not auto:
            open_report(report_path)
        return

    print_diff_summary(diff)

    # ── Step 3: Confirm ─────────────────────────────────────────────────────
    if not auto:
        print()
        if not ui.confirm("Apply these changes to the target tenant?", default=True):
            ui.warn("Sync cancelled. No changes were made.")
            report_path = gen_report(diff, src, None, REPORT_FILE)
            ui.ok(f"Report (no changes applied) → {report_path}")
            return

    # ── Step 4: Apply ───────────────────────────────────────────────────────
    ui.section("Applying changes")
    client_b = make_client(cfg["tenant_b"])
    result = None
    try:
        client_b.authenticate()
        result = apply_diff(
            client_b, diff, src,
            dry_run=False,
            no_delete=cfg["sync"].get("no_delete", False),
            sync_sensitive=cfg["sync"].get("sync_sensitive", False),
        )

        # ── Step 5: Activate ────────────────────────────────────────────────
        if cfg["sync"].get("auto_activate", True):
            ui.section("Activating changes")
            try:
                client_b.activate()
                ui.ok("Changes activated in target tenant.")
            except Exception as e:
                ui.warn(f"Activation failed: {e} — activate manually in ZIA console.")
    finally:
        client_b.logout()

    # ── Step 6: Report ──────────────────────────────────────────────────────
    ui.section("Summary")
    ui.summary_table([
        ("Applied:",  result["ok"],      ui.GRN),
        ("Errors:",   result["errors"],  ui.RED if result["errors"] else ui.DIM),
        ("Skipped:",  result["skipped"], ui.DIM),
    ])

    if result["error_details"]:
        print()
        ui.warn("Failed operations:")
        for e in result["error_details"]:
            ui.error(f"{e['action']} {e['resource']}/{e['name']}: {e['error'][:80]}")

    log_path = save_log({"diff_summary": diff.get("summary"), "result": result})
    ui.info(f"Log saved → {log_path.name}")

    report_path = gen_report(diff, src, result, REPORT_FILE)
    ui.ok(f"Report → {report_path}")
    if not auto:
        open_report(report_path)


def cmd_report():
    """Open the most recently generated HTML report in the default browser."""
    if REPORT_FILE.exists():
        ui.ok(f"Opening report: {REPORT_FILE}")
        open_report(REPORT_FILE)
    else:
        ui.warn("No report found. Run a sync first.")


def cmd_schedule():
    """Show the current cron schedule and offer to set up or remove automatic sync."""
    from scheduler import setup_schedule, show_schedule, remove_schedule
    ui.header("ZIA Sync — Scheduler")
    show_schedule()
    print()
    choice = ui.ask("What would you like to do? (setup/remove)", default="setup")
    if choice == "setup":
        setup_schedule()
    elif choice == "remove":
        remove_schedule()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Parse command-line arguments and dispatch to the appropriate command function.

    Available commands (first positional argument):
      setup     — Run the setup wizard to configure tenant credentials.
      backup    — Back up both tenants without syncing.
      dry-run   — Show what would change without applying anything.
      report    — Open the latest HTML report in the browser.
      schedule  — Set up or remove the automatic sync cron job.
      sync      — Full sync (default if no command is given).
      --auto    — Same as sync, with no confirmation prompt (for cron use).

    First-time setup: if no configuration exists and the command is not 'setup',
    the setup wizard runs automatically before the requested command.
    """
    args = sys.argv[1:]
    command = args[0] if args else "sync"
    auto = "--auto" in args

    ui.header("ZIA Tenant Sync Tool")

    # First-time setup check
    if command not in ("setup",) and not is_configured():
        ui.warn("No configuration found. Starting setup wizard...")
        print()
        if not setup_wizard(reconfigure=False):
            sys.exit(1)
        print()

    cfg = load_config()

    if command == "setup":
        cmd_setup()

    elif command == "backup":
        if not cfg:
            ui.error("Not configured. Run: python3 sync.py setup")
            sys.exit(1)
        cmd_backup(cfg, "both")
        ui.ok("Backup complete.")

    elif command == "dry-run":
        cmd_dry_run(cfg)

    elif command == "report":
        cmd_report()

    elif command == "schedule":
        cmd_schedule()

    elif command in ("sync", "--auto"):
        cmd_sync(cfg, auto=auto)

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
