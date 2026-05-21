"""
Config management — reads/writes config.json, runs setup wizard.
"""
import json
from pathlib import Path

import ui
from zia_client import ZIAClient

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "tenant_a": {
        "label": "Source Tenant (A)",
        "cloud": "",
        "username": "",
        "password": "",
        "api_key": "",
    },
    "tenant_b": {
        "label": "Target Tenant (B)",
        "cloud": "",
        "username": "",
        "password": "",
        "api_key": "",
    },
    "sync": {
        "report_only": False,
        "dry_run_default": False,
        "auto_activate": True,
        "no_delete": False,
        "schedule_cron": "",
        "sync_sensitive": False,  # users, admin users, groups — off by default
    },
}

KNOWN_CLOUDS = [
    "zsapi.zscaler.net",
    "zsapi.zscloud.net",
    "zsapi.zscalerone.net",
    "zsapi.zscalertwo.net",
    "zsapi.zscalerthree.net",
    "zsapi.zscalerbeta.net",
    "zsapi.zscalergov.net",
]


def load() -> dict:
    """Load and return the config from config.json.

    Returns an empty dict if the file does not exist (not yet configured).
    """
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def save(cfg: dict):
    """Write the config dict to config.json as formatted JSON."""
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def tenant_configured(cfg: dict, key: str) -> bool:
    """Return True if the named tenant has all required credentials."""
    tenant = cfg.get(key, {})
    return bool(
        tenant.get("cloud")
        and tenant.get("username")
        and tenant.get("password")
        and tenant.get("api_key")
    )


def is_configured() -> bool:
    """Return True if the source tenant (tenant_a) has all required credentials.

    Checks for non-empty cloud, username, password, and api_key. Used at startup
    to decide whether to launch the setup wizard automatically.
    """
    cfg = load()
    return tenant_configured(cfg, "tenant_a")


def is_report_only(cfg: dict | None = None) -> bool:
    """Return True if the config is a single-tenant report profile."""
    cfg = cfg if cfg is not None else load()
    return bool(cfg.get("sync", {}).get("report_only")) or not tenant_configured(cfg, "tenant_b")


def test_connection(label: str, cloud: str, username: str, password: str, api_key: str) -> bool:
    """Attempt to authenticate against a ZIA tenant and immediately log out.

    Prints a success or failure message inline (no newline before calling).
    Used during setup to validate credentials before saving.

    Returns:
        True if authentication succeeded, False otherwise.
    """
    print(f"\n  Testing connection to {label}...", end=" ", flush=True)
    try:
        client = ZIAClient(cloud, username, password, api_key)
        client.authenticate()
        client.logout()
        print(ui._c(ui.GRN, "✓ Connected"))
        return True
    except Exception as e:
        print(ui._c(ui.RED, f"✗ Failed: {str(e)[:80]}"))
        return False


def setup_wizard(reconfigure: bool = False):
    """Run the interactive first-time (or re-configuration) setup wizard.

    Guides the user through entering credentials for either a single report
    tenant or both source/target sync tenants, tests each connection, then asks
    for sync preferences when a target tenant is configured. Saves the result to
    config.json.

    If reconfigure=False and a config already exists, previously entered values
    are shown as defaults so the user can keep them by pressing Enter.

    Args:
        reconfigure: If True, start from a blank config (ignore any existing values).

    Returns:
        True if setup completed and config was saved, False if aborted by the user.
    """
    ui.header("ZIA Sync — Setup Wizard")
    print(f"\n  {ui._c(ui.DIM, 'This will configure ZIA tenant credentials for reports or sync.')}")
    print(f"  {ui._c(ui.DIM, 'Credentials are stored in config.json in this directory.')}\n")

    existing = load() if not reconfigure else {}
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy

    existing_report_only = existing.get("sync", {}).get("report_only")
    if existing_report_only is None:
        existing_report_only = bool(existing) and not tenant_configured(existing, "tenant_b")

    ui.section("Mode")
    print(f"  {ui._c(ui.DIM, 'Report-only mode stores one tenant and generates inventory HTML reports.')}")
    print(f"  {ui._c(ui.DIM, 'Sync mode stores source and target tenants and can migrate settings.')}")
    report_only = ui.confirm(
        "Use report-only mode (single tenant, no target sync)?",
        default=bool(existing_report_only),
    )
    cfg["sync"]["report_only"] = report_only

    tenant_prompts = [("tenant_a", "Report")] if report_only else [
        ("tenant_a", "Source"),
        ("tenant_b", "Target"),
    ]

    for key, label_default in tenant_prompts:
        ui.section(f"{label_default} Tenant")
        prev = existing.get(key, {})

        # Cloud selection
        print(f"\n  Known clouds:")
        for i, c in enumerate(KNOWN_CLOUDS, 1):
            print(f"    {ui._c(ui.DIM, str(i)+'.')} {c}")

        cloud_in = ui.ask(f"{label_default} cloud (number or full hostname)",
                          default=prev.get("cloud", ""))
        if cloud_in and cloud_in.isdigit():
            idx = int(cloud_in) - 1
            if 0 <= idx < len(KNOWN_CLOUDS):
                cloud_in = KNOWN_CLOUDS[idx]
        cfg[key]["cloud"] = cloud_in or prev.get("cloud", "")

        cfg[key]["username"] = ui.ask("Admin username (e.g. admin@company.com)",
                                       default=prev.get("username", ""))
        password_prompt = "Admin password"
        if prev.get("password") and not reconfigure:
            password_prompt += " (press Enter to keep existing)"
        password = ui.ask_password(password_prompt)
        cfg[key]["password"] = password or prev.get("password", "")
        cfg[key]["api_key"]  = ui.ask("API Key",
                                       default=prev.get("api_key", ""))
        cfg[key]["label"]    = ui.ask("Label (for reports)",
                                       default=prev.get("label", label_default))

        ok = test_connection(cfg[key]["label"], cfg[key]["cloud"],
                              cfg[key]["username"], cfg[key]["password"],
                              cfg[key]["api_key"])
        if not ok:
            if not ui.confirm("Connection failed. Save anyway?", default=False):
                ui.warn("Setup aborted.")
                return False

    if report_only:
        ui.section("Report Settings")
        ui.ok("Report-only mode enabled. Sync, dry-run, and schedule commands will stay disabled until you add a target tenant.")
        save(cfg)
        ui.ok(f"Config saved → {CONFIG_PATH}")
        return True

    # Sync settings
    ui.section("Sync Settings")
    cfg["sync"]["no_delete"] = not ui.confirm(
        "Delete objects in target that don't exist in source?", default=True)
    cfg["sync"]["auto_activate"] = ui.confirm(
        "Automatically activate changes in target after sync?", default=True)

    print()
    ui.warn("Sensitive resources: users, admin users, groups")
    print(f"  {ui._c(ui.DIM, 'These control who has access and with what permissions.')}")
    print(f"  {ui._c(ui.DIM, 'Syncing them can lock people out or grant unintended access.')}")
    cfg["sync"]["sync_sensitive"] = ui.confirm(
        "Include users, admin users and groups in sync?", default=False)

    save(cfg)
    ui.ok(f"Config saved → {CONFIG_PATH}")
    return True
