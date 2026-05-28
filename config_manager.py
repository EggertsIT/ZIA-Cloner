"""
Config management — reads/writes config.json, runs setup wizard.
"""
import json
from pathlib import Path

import ui
from app_paths import APP_DIR
from secret_store import protect_config, unprotect_config
from zia_client import AUTH_MODE_LEGACY, AUTH_MODE_ONEAPI, ZIAClient, normalise_legacy_cloud

CONFIG_PATH = APP_DIR / "config.json"

DEFAULT_CONFIG = {
    "tenant_a": {
        "label": "Source Tenant (A)",
        "auth_mode": AUTH_MODE_ONEAPI,
        "oneapi_cloud": "production",
        "client_id": "",
        "client_secret": "",
        "vanity_domain": "",
        "partner_id": "",
        "cloud": "",
        "username": "",
        "password": "",
        "api_key": "",
    },
    "tenant_b": {
        "label": "Target Tenant (B)",
        "auth_mode": AUTH_MODE_ONEAPI,
        "oneapi_cloud": "production",
        "client_id": "",
        "client_secret": "",
        "vanity_domain": "",
        "partner_id": "",
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
        "include_slow_readonly": False,
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

KNOWN_ONEAPI_CLOUDS = [
    "production",
    "beta",
    "alpha",
    "zscaler",
    "zscalerone",
    "zscalertwo",
    "zscalerthree",
    "zscloud",
    "zscalerbeta",
    "zspreview",
]


def load() -> dict:
    """Load and return the config from config.json.

    Returns an empty dict if the file does not exist (not yet configured).
    """
    if CONFIG_PATH.exists():
        return unprotect_config(json.loads(CONFIG_PATH.read_text()))
    return {}


def save(cfg: dict):
    """Write the config dict to config.json as formatted JSON."""
    protected = protect_config(json.loads(json.dumps(cfg)))
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(protected, indent=2), encoding="utf-8")


def tenant_value(tenant: dict, *names: str) -> str:
    """Read either the tool's snake_case or SDK-style camelCase config keys."""
    for name in names:
        value = tenant.get(name)
        if value:
            return value
    return ""


def tenant_auth_mode(tenant: dict) -> str:
    """Return the tenant authentication mode, defaulting old configs to legacy."""
    mode = (tenant.get("auth_mode") or AUTH_MODE_LEGACY).strip().lower()
    if mode in ("oauth", "oauth2", "zidentity", AUTH_MODE_ONEAPI):
        return AUTH_MODE_ONEAPI
    return AUTH_MODE_LEGACY


def missing_auth_fields(tenant: dict) -> list[str]:
    """Return the required auth fields that are missing for a tenant block."""
    if tenant_auth_mode(tenant) == AUTH_MODE_ONEAPI:
        required = [
            ("client_id", "clientId"),
            ("client_secret", "clientSecret"),
            ("vanity_domain", "vanityDomain"),
        ]
        return [names[0] for names in required if not tenant_value(tenant, *names)]
    required = [
        ("cloud", "zia_cloud", "ziaCloud"),
        ("username", "userName"),
        ("password",),
        ("api_key", "apiKey"),
    ]
    return [names[0] for names in required if not tenant_value(tenant, *names)]


def tenant_configured(cfg: dict, key: str) -> bool:
    """Return True if the named tenant has all required credentials."""
    tenant = cfg.get(key, {})
    return bool(tenant) and not missing_auth_fields(tenant)


def is_configured() -> bool:
    """Return True if the source tenant (tenant_a) has required auth fields."""
    cfg = load()
    return tenant_configured(cfg, "tenant_a")


def is_report_only(cfg: dict | None = None) -> bool:
    """Return True if the config is a single-tenant report profile."""
    cfg = cfg if cfg is not None else load()
    return bool(cfg.get("sync", {}).get("report_only")) or not tenant_configured(cfg, "tenant_b")


def test_connection(label: str, tenant_cfg: dict) -> bool:
    """Attempt to authenticate against a ZIA tenant and immediately log out.

    Prints a success or failure message inline (no newline before calling).
    Used during setup to validate credentials before saving.

    Returns:
        True if authentication succeeded, False otherwise.
    """
    print(f"\n  Testing connection to {label}...", end=" ", flush=True)
    try:
        client = ZIAClient.from_config(tenant_cfg)
        print(f"\n  Auth mode: {client.auth_mode}; API: {client.base}", end=" ", flush=True)
        client.authenticate()
        client.logout()
        print(ui._c(ui.GRN, "✓ Connected"))
        return True
    except Exception as e:
        print(ui._c(ui.RED, f"✗ Failed: {str(e)[:1000]}"))
        return False


def _prompt_legacy_tenant(cfg: dict, key: str, label_default: str, prev: dict, reconfigure: bool):
    """Prompt for legacy ZIA API credentials."""
    cfg[key]["auth_mode"] = AUTH_MODE_LEGACY

    print(f"\n  Known legacy clouds:")
    for i, c in enumerate(KNOWN_CLOUDS, 1):
        print(f"    {ui._c(ui.DIM, str(i)+'.')} {c}")

    cloud_in = ui.ask(f"{label_default} cloud (number or full hostname)",
                      default=prev.get("cloud", ""))
    if cloud_in and cloud_in.isdigit():
        idx = int(cloud_in) - 1
        if 0 <= idx < len(KNOWN_CLOUDS):
            cloud_in = KNOWN_CLOUDS[idx]
    cfg[key]["cloud"] = normalise_legacy_cloud(cloud_in or prev.get("cloud", ""))

    cfg[key]["username"] = ui.ask("Admin username (e.g. admin@company.com)",
                                  default=prev.get("username", ""))
    password_prompt = "Admin password"
    if prev.get("password") and not reconfigure:
        password_prompt += " (press Enter to keep existing)"
    password = ui.ask_password(password_prompt)
    cfg[key]["password"] = password or prev.get("password", "")
    cfg[key]["api_key"] = ui.ask("API Key", default=prev.get("api_key", ""))


def _prompt_oneapi_tenant(cfg: dict, key: str, prev: dict, reconfigure: bool):
    """Prompt for OneAPI/Zidentity OAuth credentials."""
    cfg[key]["auth_mode"] = AUTH_MODE_ONEAPI

    print(f"\n  Known OneAPI clouds:")
    for i, c in enumerate(KNOWN_ONEAPI_CLOUDS, 1):
        print(f"    {ui._c(ui.DIM, str(i)+'.')} {c}")

    vanity = tenant_value(prev, "vanity_domain", "vanityDomain")
    oneapi_cloud = tenant_value(prev, "oneapi_cloud")
    if not oneapi_cloud and tenant_auth_mode(prev) == AUTH_MODE_ONEAPI:
        oneapi_cloud = prev.get("cloud", "")

    cloud_in = ui.ask("OneAPI cloud (number or cloud name)",
                      default=oneapi_cloud or "production")
    if cloud_in and cloud_in.isdigit():
        idx = int(cloud_in) - 1
        if 0 <= idx < len(KNOWN_ONEAPI_CLOUDS):
            cloud_in = KNOWN_ONEAPI_CLOUDS[idx]
    cfg[key]["oneapi_cloud"] = cloud_in or oneapi_cloud or "production"
    cfg[key]["vanity_domain"] = ui.ask("Vanity domain (without .zslogin.net)",
                                       default=vanity)
    cfg[key]["client_id"] = ui.ask("Client ID",
                                   default=tenant_value(prev, "client_id", "clientId"))

    secret_prompt = "Client secret"
    if tenant_value(prev, "client_secret", "clientSecret") and not reconfigure:
        secret_prompt += " (press Enter to keep existing)"
    secret = ui.ask_password(secret_prompt)
    cfg[key]["client_secret"] = secret or tenant_value(prev, "client_secret", "clientSecret")
    cfg[key]["partner_id"] = ui.ask("Partner ID (optional)",
                                    default=tenant_value(prev, "partner_id", "partnerId"))


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

    default_oneapi = True
    if existing:
        default_oneapi = tenant_auth_mode(existing.get("tenant_a", {})) == AUTH_MODE_ONEAPI
    use_oneapi = ui.confirm(
        "Use OneAPI OAuth/Zidentity authentication?",
        default=default_oneapi,
    )
    auth_mode = AUTH_MODE_ONEAPI if use_oneapi else AUTH_MODE_LEGACY

    tenant_prompts = [("tenant_a", "Report")] if report_only else [
        ("tenant_a", "Source"),
        ("tenant_b", "Target"),
    ]

    for key, label_default in tenant_prompts:
        ui.section(f"{label_default} Tenant")
        prev = existing.get(key, {})

        if auth_mode == AUTH_MODE_ONEAPI:
            _prompt_oneapi_tenant(cfg, key, prev, reconfigure)
        else:
            _prompt_legacy_tenant(cfg, key, label_default, prev, reconfigure)

        cfg[key]["label"] = ui.ask("Label (for reports)",
                                   default=prev.get("label", label_default))

        ok = test_connection(cfg[key]["label"], cfg[key])
        if not ok:
            if not ui.confirm("Connection failed. Save anyway?", default=False):
                ui.warn("Setup aborted.")
                return False

    if report_only:
        ui.section("Report Settings")
        cfg["sync"]["include_slow_readonly"] = ui.confirm(
            "Include slow read-only inventory endpoints? (network applications can take several minutes)",
            default=False,
        )
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
    cfg["sync"]["include_slow_readonly"] = ui.confirm(
        "Include slow read-only inventory endpoints? (network applications can take several minutes)",
        default=False,
    )

    save(cfg)
    ui.ok(f"Config saved → {CONFIG_PATH}")
    return True
