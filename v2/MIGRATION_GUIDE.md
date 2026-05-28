# ZIA Migration Guide — What Can & Cannot Be Synced

> Based on the Zscaler ZIA REST API (zscaler-sdk-python v78 modules, 2025).

---

## Category A — Fully Syncable via API ✅

All CRUD operations (GET/POST/PUT/DELETE) supported. The sync tool handles these automatically.

| Resource | API Endpoint | Notes |
|----------|-------------|-------|
| Rule Labels | `ruleLabels` | Sync first — all rules reference labels |
| Departments | `departments` | |
| Groups | `groups` | |
| Time Intervals | `timeIntervals` | |
| Workload Groups | `workloadGroups` | |
| Custom URL Categories | `urlCategories?customOnly=true` | Predefined categories cannot be created/deleted |
| IP Destination Groups | `ipDestinationGroups` | |
| IP Source Groups | `ipSourceGroups` | |
| Custom Network Services | `networkServices?customOnly=true` | Predefined services cannot be modified |
| Network Service Groups | `networkServiceGroups` | |
| Network Application Groups | `networkApplicationGroups` | |
| Bandwidth Classes | `bandwidthClasses` | |
| Custom File Types | `customFileTypes` | |
| Custom DLP Dictionaries | `dlpDictionaries?customOnly=true` | Predefined dictionaries cannot be modified |
| Custom DLP Engines | `dlpEngines?customOnly=true` | |
| DLP Notification Templates | `dlpNotificationTemplates` | |
| Static IPs | `staticIP` | |
| VPN Credentials | `vpnCredentials` | ⚠ Pre-shared keys excluded — see Category B |
| PAC Files | `pacFiles` | |
| ZPA Gateways | `zpaGateways` | Requires ZPA integration on target |
| Locations | `locations` | |
| Location Groups | `locationGroups` | May 404 on lower tiers |
| GRE Tunnels | `greTunnels` | |
| Users | `users` | ⚠ Passwords excluded — see Category B |
| Alert Subscriptions | `alertSubscriptions` | |
| Forwarding Rules | `forwardingRules` | |
| URL Filtering Rules | `urlFilteringRules` | Default/system rules cannot be deleted |
| Cloud Firewall Rules | `firewallFilteringRules` | Default/system rules cannot be deleted |
| Firewall DNS Rules | `firewallDnsRules` | Requires DNS Control feature |
| Firewall IPS Rules | `firewallIpsRules` | Requires IPS feature |
| NAT Control Rules (DNAT) | `dnatRules` | Requires NAT Control feature |
| SSL Inspection Rules | `sslInspectionRules` | |
| Sandbox Rules | `sandboxRules` | Requires Sandbox feature |
| Bandwidth Control Rules | `bandwidthControlRules` | |
| File Type Control Rules | `fileTypeRules` | |
| DLP Web Rules | `webDlpRules` | |
| Cloud App Control Rules | `webApplicationRules/{type}` | ⚠ Multiple rule types exist — see note |
| CASB DLP Rules | `casbDlpRules` | Requires CASB license |
| CASB Malware Rules | `casbMalwareRules` | Requires CASB license |
| Cloud NSS Feeds | `nssFeeds` | |
| Admin Users | `adminUsers` | ⚠ Passwords excluded — see Category B |

**Total: 40 resource types fully syncable**

---

## Category B — Partially Syncable ⚠️

API supports read + write, but with important caveats requiring manual follow-up.

### Settings Objects (GET + PUT, applied as-is)

| Resource | API Endpoint | Caveat |
|----------|-------------|--------|
| Authentication Settings | `authSettings` | SSO/SAML config references external IdP — verify IdP metadata is correctly configured in target |
| Advanced Settings | `advancedSettings` | Review all settings after sync; some may reference tenant-specific values |
| Security Policy (Basic) | `security` | Allow/blocklists are synced; verify after |
| Security Policy (Advanced) | `security/advanced` | Custom blacklist URLs synced |
| ATP Settings | `cyberThreatProtection/advancedThreatSettings` | |
| ATP Security Exceptions | `cyberThreatProtection/securityExceptions` | |
| Malware Policy | `cyberThreatProtection/malwarePolicy` | |
| Malware Settings | `cyberThreatProtection/malwareSettings` | |
| FTP Settings | `ftpSettings` | |
| Browser Control Settings | `browserControlSettings` | |
| End User Notification | `eun` | Block page customizations synced |
| Mobile Threat Settings | `mobileAdvanceThreatSettings` | |

### Secrets Not Exported (manual re-entry required)

| Resource | What to do manually |
|----------|---------------------|
| **VPN Credentials** — pre-shared keys | Re-enter PSKs in target: Admin Portal → Traffic Forwarding → VPN Credentials |
| **Users** — passwords | Users need to set new passwords or use SSO |
| **Admin Users** — passwords | Admins need to reset passwords after migration |

### Cloud App Control Rules — Multiple Types

The `webApplicationRules` endpoint requires a `{rule_type}` parameter. Rule types include:
`SOCIAL_NETWORKING`, `STREAMING`, `COLLABORATION`, `FILE_SHARING`, `EMAIL`, `GAMES`,
`BUSINESS_PRODUCTIVITY`, and many more.

**The sync tool currently only handles `SOCIAL_NETWORKING`.**

To sync additional rule types, add them to `resources.py` as separate entries (copy the `cloud_app_control_rules` entry and change the endpoint and key name for each type).

---

## Category C — Read-Only, Manual Action Required 🔴

These settings **cannot be written via API**. They must be configured manually in the target tenant after migration.

### Certificates

| Resource | What to do |
|----------|-----------|
| **Intermediate CA Certificates** | Admin Portal → Policy → SSL Inspection → Intermediate CA Certificate. Re-import each cert (you need the original certificate file + private key). |
| **Root CA Certificates** | Not exposed via API. Re-import trusted root CAs manually. |

### DLP Reference Data (requires re-upload of source data)

| Resource | What to do |
|----------|-----------|
| **IDM Profiles** (Indexed Document Matching) | Admin Portal → Policy → DLP → Indexed Documents. Re-upload the original documents to re-index. |
| **EDM Schemas** (Exact Data Match) | Admin Portal → Policy → DLP → Exact Data Match. Re-upload the original CSV/data source. |
| **ICAP Servers** | Admin Portal → Administration → ICAP Servers. Manually reconfigure each server. |

### Predefined / Cloud-Managed (managed by Zscaler)

| Resource | Notes |
|----------|-------|
| Predefined URL Categories | Managed by Zscaler. Custom overrides (URLs added to predefined categories) ARE synced via `url_categories`. |
| Predefined Network Services | Managed by Zscaler. Cannot be created or deleted. |
| Admin Roles | Predefined by Zscaler. **Custom admin roles must be manually recreated** in target tenant if you have any. |
| ZIA Virtual IPs | Cloud-managed, tenant-specific. |
| Egress IP Groups | Cloud-managed by Zscaler. |
| Traffic Datacenters | Cloud-managed. |

### Organization-Specific (not transferable)

| Resource | Notes |
|----------|-------|
| Organization Information | Company name, contact details. Update manually: Admin Portal → Administration → Company Profile. |
| Subscription / License | Not transferable. Ensure target tenant has equivalent feature licenses before syncing. **Check license before syncing CASB/Sandbox/IPS rules.** |
| Audit Logs | Historical logs stay in source tenant. |
| Shadow IT Reports | Not transferable. |
| Browser Isolation Profiles | Read-only (CBI license required). Profiles must be manually recreated in target. |

---

## Pre-Migration Checklist

Before running the migration:

- [ ] Target tenant has equivalent **feature licenses** (Sandbox, IPS, CASB, CBI, DNS Control, NAT)
- [ ] Note down all **VPN pre-shared keys** from source (not exported)
- [ ] Export/backup all **Intermediate CA Certificates** + private keys (not exported)
- [ ] Note any **custom Admin Roles** (not synced)
- [ ] Have original **IDM documents** and **EDM data sources** ready if DLP is used
- [ ] Verify the **IdP metadata** URL/certificate in target for SAML/SSO (auth_settings will be overwritten)
- [ ] Run `python3 sync.py dry-run` first and review the report

## Post-Migration Checklist

After running the migration:

- [ ] Re-enter **VPN pre-shared keys** for all VPN credentials
- [ ] Re-import **Intermediate CA certificates** for SSL inspection
- [ ] Re-configure **ICAP servers** if DLP uses them
- [ ] Re-upload **IDM/EDM source data** if applicable
- [ ] Recreate **custom Admin Roles** if any
- [ ] Set passwords for **Admin Users** and notify them
- [ ] Verify **Authentication Settings** — test SSO login
- [ ] Check **Cloud App Control** rule types beyond SOCIAL_NETWORKING
- [ ] Activate changes in target: Admin Portal → Activate or `python3 sync.py` will activate automatically
- [ ] Validate policy by testing a sample user workflow

---

## Feature License Dependencies

Some resources will fail to sync (404) if the target tenant doesn't have the required license:

| Feature | Resources affected |
|---------|-------------------|
| Sandbox | `sandboxRules` |
| IPS | `firewall_ips_rules` |
| DNS Control | `firewall_dns_rules`, `dns_rules` |
| NAT Control | `nat_control_rules` |
| CASB | `casb_dlp_rules`, `casb_malware_rules` |
| Cloud Browser Isolation | `browser_isolation_profiles` |
| Bandwidth Control | `bandwidth_control_rules`, `bandwidth_classes` |
| Location Groups | `location_groups` (some tiers) |

The sync tool handles these gracefully — it logs the error and continues. Check the report for skipped resources.
