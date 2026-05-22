# ZIA Sync Tool

Synchronizes settings between two Zscaler Internet Access (ZIA) tenants, or
generates a full single-tenant inventory report. New setups use OneAPI
OAuth/Zidentity by default, with legacy ZIA API key authentication still
available for tenants that have not moved to Zidentity.
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

A wizard asks whether you want report-only mode and which authentication mode to
use.

- Report-only mode needs one tenant and generates HTML inventory reports.
- Sync mode needs both source and target tenants and can migrate settings.
- OneAPI mode needs a Zidentity API Client ID, client secret, and vanity domain.
- Legacy mode needs the old ZIA admin username, password, API key, and cloud.

The wizard tests the connection and saves credentials locally to `config.json`.

### Step 2 — Run a sync or report

```bash
python3 sync.py              # sync mode: run a guarded sync
python3 sync.py full-report  # report-only mode: generate inventory HTML
```

In sync mode, the tool will:
1. Back up both tenants
2. Compute the diff and show exactly what will change
3. Ask for your confirmation
4. Apply all changes to the target tenant
5. Activate and open an HTML report in your browser

In report-only mode, `python3 sync.py` also generates a full inventory report for
the configured tenant.

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
python3 sync.py backup [a|b|both]
                           # Backup configured tenant(s) without syncing
python3 sync.py report     # Open the latest sync/diff report in the browser
python3 sync.py full-report [a|b|both]
                           # Generate a full API inventory report as HTML
python3 sync.py --auto     # Full sync, no prompts (used by cron)
```

---

## What gets synced

141 resource definitions are covered. 41 support full CRUD, 12 are settings
objects (GET+PUT), and 88 are report-only/read-only inventory endpoints.

| Category | Resources |
|----------|-----------|
| **Rules & Labels** | Rule labels, URL filtering, Cloud firewall, Firewall DNS, Firewall IPS, NAT/DNAT, SSL inspection, Sandbox, Bandwidth control, File type control, DLP web rules, Cloud app control, CASB DLP, CASB Malware |
| **Network Objects** | IP destination groups, IP source groups, Custom network services, Network service groups, Network application groups, Bandwidth classes, Custom file types |
| **Traffic Forwarding** | Static IPs, VPN credentials, GRE tunnels, Locations, Location groups, PAC files, ZPA gateways, Forwarding rules, data centers, DC exclusions, extranets, IPv6 config, subclouds, dedicated IP gateways, VIP inventories |
| **DLP** | Custom dictionaries, Custom engines, Notification templates, incident receivers, ICAP/IDM/EDM references, Cloud-to-Cloud IR, lite/all DLP inventories |
| **URL** | Custom URL categories (incl. overrides in predefined categories) |
| **Identity** | Users, Groups, Departments, Admin users, Alert subscriptions |
| **Settings** | Auth settings, Advanced settings, Security policy, ATP, Malware protection, FTP control, Browser control, End user notification, Mobile threat protection |
| **SaaS / Cloud Apps** | Cloud App Control rule types, cloud app policy/SSL policy apps, cloud app instances, risk profiles, tenancy restrictions, SaaS tenants, SaaS scan info, domain profiles, quarantine templates, email labels |
| **Certificates / Policy Export** | Intermediate CA certificate inventory, ready-to-use certificates, per-certificate cert/CSR/public-key fetches, auth exempted URLs, raw policy export |
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
python3 sync.py full-report       # report-only: configured tenant; sync mode: both tenants
python3 sync.py full-report a     # source tenant only
python3 sync.py full-report b     # target tenant only
```

The inventory report is written to `backups/full_report.html`. Secret-looking
fields such as passwords, tokens, API keys, private keys, and pre-shared keys are
redacted in the HTML output.

For endpoint-level implementation status, see
[`API_COVERAGE_MATRIX.md`](API_COVERAGE_MATRIX.md). It is generated from
`resources.py` and compares the tool against the official SDK ZIA endpoint
surface when a local SDK checkout is available:

```bash
python3 tools/generate_api_coverage.py
```

---

## Files

```
sync.py              ← Only file you need to run
API_COVERAGE_MATRIX.md ← Endpoint-by-endpoint API coverage matrix
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
zia_client.py        ← ZIA API client (OneAPI/legacy auth, pagination, rate-limit retry)
engine.py            ← Backup / diff / migrate logic
resources.py         ← All 141 resource definitions with metadata
config_manager.py    ← Setup wizard, config read/write
scheduler.py         ← Cron integration
report_gen.py        ← HTML report generator
ui.py                ← Terminal colors and prompts
tools/generate_api_coverage.py
                     ← Regenerates the API coverage matrix
```

---

## Requirements

- Python 3.10 or later
- No external packages — standard library only
- Network access to the configured ZIA tenant(s)
- OneAPI/Zidentity API Client credentials for each configured tenant, or legacy
  ZIA admin credentials + API key when legacy auth is selected

### OneAPI Authentication

Create an API role/client in Zidentity, following Zscaler's
[OneAPI getting started guide](https://automate.zscaler.com/docs/getting-started/getting-started),
then run:

```bash
python3 sync.py setup
```

Choose OneAPI when prompted and enter:

- Client ID
- Client secret
- Vanity domain, for example `acme` from `https://acme.zslogin.net`
- Optional cloud name, for example `production` or `beta`
- Optional partner ID

This implementation uses OneAPI client-secret OAuth and sends API calls to the
OneAPI ZIA path (`/zia/api/v1`). Private-key JWT auth is not implemented because
the tool intentionally has no external Python dependencies.

### Legacy ZIA API Key

If your tenant is not on Zidentity/OneAPI, choose legacy authentication in the
setup wizard.

Admin Portal → Administration → API Key Management → Add API Key

---

## Validation

The tool was validated with a self-migration test (tenant synced against itself):
- **0 false positives** in diff (list ordering normalized, computed fields excluded)
- **0 errors** in dry-run apply
- Rate limiting handled automatically with exponential backoff retry
