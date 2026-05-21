# ZIA Sync Tool

Synchronizes settings between two Zscaler Internet Access (ZIA) tenants.
Backup → Diff → Report → Apply — one command, no technical knowledge required.

---

> **Disclaimer:** This tool is provided as-is, without warranty of any kind.
> Use at your own risk. It is not officially supported or maintained, and no
> guarantee is made regarding correctness, completeness, or fitness for any
> particular purpose. Always run a dry-run first and verify results before
> applying changes to a production tenant. The authors accept no liability
> for data loss, misconfiguration, or any other damage resulting from use.

---

## Quick Start

### Step 1 — First-time setup (2 minutes)

```bash
python3 sync.py setup
```

A wizard guides you through entering credentials for both tenants and tests the connection.
Credentials are saved locally to `config.json`.

### Step 2 — Run a sync

```bash
python3 sync.py
```

The tool will:
1. Back up both tenants
2. Compute the diff and show exactly what will change
3. Ask for your confirmation
4. Apply all changes to the target tenant
5. Activate and open an HTML report in your browser

### Step 3 — Preview without changing anything

```bash
python3 sync.py dry-run
```

### Step 4 — Set up automatic sync (e.g. daily at 2 AM)

```bash
python3 sync.py schedule
```

Writes a cron job. After that, sync runs automatically in the background.

### Other commands

```bash
python3 sync.py backup     # Backup both tenants without syncing
python3 sync.py report     # Open the latest sync/diff report in the browser
python3 sync.py full-report [a|b|both]
                           # Generate a full API inventory report as HTML
python3 sync.py --auto     # Full sync, no prompts (used by cron)
```

---

## What gets synced

65 resource types are covered. 41 support full CRUD, 12 are settings objects (GET+PUT).

| Category | Resources |
|----------|-----------|
| **Rules & Labels** | Rule labels, URL filtering, Cloud firewall, Firewall DNS, Firewall IPS, NAT/DNAT, SSL inspection, Sandbox, Bandwidth control, File type control, DLP web rules, Cloud app control, CASB DLP, CASB Malware |
| **Network Objects** | IP destination groups, IP source groups, Custom network services, Network service groups, Network application groups, Bandwidth classes, Custom file types |
| **Traffic Forwarding** | Static IPs, VPN credentials, GRE tunnels, Locations, Location groups, PAC files, ZPA gateways, Forwarding rules |
| **DLP** | Custom dictionaries, Custom engines, Notification templates |
| **URL** | Custom URL categories (incl. overrides in predefined categories) |
| **Identity** | Users, Groups, Departments, Admin users, Alert subscriptions |
| **Settings** | Auth settings, Advanced settings, Security policy, ATP, Malware protection, FTP control, Browser control, End user notification, Mobile threat protection |
| **Admin** | Cloud NSS feeds |

> ⚠ **Secrets not exported:** VPN pre-shared keys and user/admin passwords are intentionally excluded for security. These must be re-entered manually after migration.

---

## What cannot be synced (manual steps required)

See [`MIGRATION_GUIDE.md`](MIGRATION_GUIDE.md) for the full checklist. Summary:

| Setting | Reason | Action |
|---------|--------|--------|
| Intermediate CA Certificates | Private keys not exportable via API | Re-import in Admin Portal → SSL Inspection |
| IDM / EDM profiles | Requires original source data | Re-upload documents/CSV in Admin Portal → DLP |
| ICAP servers | Not configurable via API | Reconfigure manually |
| Predefined URL categories | Managed by Zscaler | No action needed (custom overrides are synced) |
| Custom Admin Roles | No write API | Recreate manually |
| Subscription / License | Cloud-managed | Verify target has same features |
| Org information | No write API | Update manually in Admin Portal |
| Audit logs / Reports | Historical, not transferable | N/A |

---

## Report

After every sync (or dry-run), an HTML report opens automatically showing:
- Summary table: what was created / updated / deleted / unchanged
- Per-resource change details
- Read-only resources that need manual attention
- Full migration dependency order

To create an inventory report containing the full data returned by all configured
API backup endpoints, run:

```bash
python3 sync.py full-report       # source and target tenants
python3 sync.py full-report a     # source tenant only
python3 sync.py full-report b     # target tenant only
```

The inventory report is written to `backups/full_report.html`. Secret-looking
fields such as passwords, tokens, API keys, private keys, and pre-shared keys are
redacted in the HTML output.

---

## Files

```
sync.py              ← Only file you need to run
config.json          ← Tenant credentials (created by setup wizard)
MIGRATION_GUIDE.md   ← Detailed reference: what's syncable, pre/post checklist
backups/
  tenant_a.json      ← Latest backup of source tenant
  tenant_b.json      ← Latest backup of target tenant
  diff.json          ← Latest computed diff
  report.html        ← Latest sync/diff HTML report
  full_report.html   ← Latest full API inventory HTML report
  logs/              ← Per-sync JSON logs with full change history
```

Internal modules (no need to touch these):

```
zia_client.py        ← ZIA API client (auth, pagination, rate-limit retry)
engine.py            ← Backup / diff / migrate logic
resources.py         ← All 65 resource definitions with metadata
config_manager.py    ← Setup wizard, config read/write
scheduler.py         ← Cron integration
report_gen.py        ← HTML report generator
ui.py                ← Terminal colors and prompts
```

---

## Requirements

- Python 3.10 or later
- No external packages — standard library only
- Network access to both ZIA tenants
- ZIA admin credentials + API key for both tenants

### How to get your ZIA API Key

Admin Portal → Administration → API Key Management → Add API Key

---

## Validation

The tool was validated with a self-migration test (tenant synced against itself):
- **0 false positives** in diff (list ordering normalized, computed fields excluded)
- **0 errors** in dry-run apply
- Rate limiting handled automatically with exponential backoff retry
