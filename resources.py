"""
ZIA resource definitions — complete coverage based on zscaler-sdk-python v78 modules.

Each entry:
  endpoint      – ZIA API path (without /api/v1/)
  kind          – "list"     = paginated list of objects (full CRUD)
                  "settings" = single settings object (GET + PUT only)
                  "readonly" = GET only, cannot be written via API
  writable      – True if POST/PUT/DELETE supported
  id_field      – primary key (None for settings objects)
  name_field    – human-readable name for diff/dedup (None for settings)
  depends_on    – resource keys that must exist first
  skip_fields   – fields to strip before POST/PUT (secrets, computed fields)
  notes         – shown in the read-only / manual-steps report
"""

# Fields ZIA returns but rejects on write
SYSTEM_FIELDS = {
    "id", "creationTime", "lastModifiedTime", "lastModifiedBy",
    "modifiedTime", "modifiedBy", "isSystemDefined", "predefined",
    "type",  # often computed
}

RESOURCES: dict[str, dict] = {

    # ══════════════════════════════════════════════════════════════════════════
    # INFRASTRUCTURE — no dependencies, create first
    # ══════════════════════════════════════════════════════════════════════════

    "rule_labels": {
        "endpoint": "ruleLabels",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Rule labels used to tag/group rules across all policy types.",
    },
    "departments": {
        "endpoint": "departments",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "",
    },
    "groups": {
        "endpoint": "groups",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "sensitive": True,
        "notes": "⚠ SENSITIVE: Groups control access permissions. Synced only with explicit approval.",
    },
    "time_intervals": {
        "endpoint": "timeIntervals",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "",
    },
    "workload_groups": {
        "endpoint": "workloadGroups",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Workload groups for tagging cloud workloads.",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # URL / CONTENT
    # ══════════════════════════════════════════════════════════════════════════

    "url_categories": {
        "endpoint": "urlCategories?customOnly=true",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "configuredName",
        "depends_on": [],
        "skip_fields": {"dbCategorizedUrls"},
        "notes": "Custom URL categories only. Predefined categories are read-only.",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # NETWORK OBJECTS
    # ══════════════════════════════════════════════════════════════════════════

    "ip_destination_groups": {
        "endpoint": "ipDestinationGroups",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "",
    },
    "ip_source_groups": {
        "endpoint": "ipSourceGroups",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "",
    },
    "network_services": {
        "endpoint": "networkServices?customOnly=true",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Custom network services only. Predefined services are read-only.",
    },
    "network_service_groups": {
        "endpoint": "networkServiceGroups",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["network_services"],
        "skip_fields": set(),
        "notes": "",
    },
    "network_application_groups": {
        "endpoint": "networkApplicationGroups",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "",
    },
    "bandwidth_classes": {
        "endpoint": "bandwidthClasses",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Required before bandwidth_control_rules.",
    },
    "custom_file_types": {
        "endpoint": "customFileTypes",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Custom file type definitions used in file type control rules.",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # TRAFFIC FORWARDING
    # ══════════════════════════════════════════════════════════════════════════

    "static_ips": {
        "endpoint": "staticIP",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "ipAddress",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Static IPs for traffic forwarding.",
    },
    "vpn_credentials": {
        "endpoint": "vpnCredentials",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "fqdn",
        "depends_on": [],
        "skip_fields": {"preSharedKey"},
        "notes": "⚠ Pre-shared keys are NOT exported (security). Must be re-entered manually on target.",
    },
    "gre_tunnels": {
        "endpoint": "greTunnels",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "sourceIp",
        "depends_on": ["locations", "static_ips"],
        "skip_fields": set(),
        "notes": "",
    },
    "locations": {
        "endpoint": "locations",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["vpn_credentials", "groups", "static_ips"],
        "skip_fields": set(),
        "notes": "",
    },
    "location_groups": {
        "endpoint": "locationGroups",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["locations"],
        "skip_fields": set(),
        "notes": "May return 404 on lower subscription tiers.",
    },
    "pac_files": {
        "endpoint": "pacFiles",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": {"totalHits"},  # live counter, not a config value
        "notes": "",
    },
    "zpa_gateways": {
        "endpoint": "zpaGateways",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "ZPA gateways for Source IP Anchoring. Requires ZPA integration.",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # DLP
    # ══════════════════════════════════════════════════════════════════════════

    "dlp_dictionaries": {
        "endpoint": "dlpDictionaries?customOnly=true",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Custom DLP dictionaries only. Predefined dictionaries are read-only.",
    },
    "dlp_engines": {
        "endpoint": "dlpEngines?customOnly=true",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["dlp_dictionaries"],
        "skip_fields": set(),
        "notes": "Custom DLP engines only.",
    },
    "dlp_notification_templates": {
        "endpoint": "dlpNotificationTemplates",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # IDENTITY
    # ══════════════════════════════════════════════════════════════════════════

    "users": {
        "endpoint": "users",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "email",
        "depends_on": ["groups", "departments"],
        "skip_fields": {"password"},
        "sensitive": True,
        "notes": "⚠ SENSITIVE: User accounts. Synced only with explicit approval. Passwords NOT exported.",
    },
    "alert_subscriptions": {
        "endpoint": "alertSubscriptions",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "email",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Alert email subscriptions for ZIA notifications.",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # FORWARDING POLICY
    # ══════════════════════════════════════════════════════════════════════════

    "forwarding_rules": {
        "endpoint": "forwardingRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["locations", "location_groups", "groups", "departments",
                       "pac_files", "zpa_gateways"],
        "skip_fields": set(),
        "notes": "",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # POLICY RULES — all depend on labels + identity + network objects
    # ══════════════════════════════════════════════════════════════════════════

    "url_filtering_rules": {
        "endpoint": "urlFilteringRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "url_categories", "groups", "departments",
                       "locations", "location_groups", "time_intervals"],
        "skip_fields": set(),
        "notes": "Default/system rules cannot be deleted, only updated.",
    },
    "firewall_rules": {
        "endpoint": "firewallFilteringRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "ip_destination_groups", "ip_source_groups",
                       "network_services", "network_service_groups",
                       "network_application_groups", "time_intervals",
                       "groups", "departments", "locations", "location_groups",
                       "workload_groups"],
        "skip_fields": set(),
        "notes": "Default/system rules cannot be deleted.",
    },
    "firewall_dns_rules": {
        "endpoint": "firewallDnsRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "ip_source_groups", "groups", "departments",
                       "locations", "location_groups", "time_intervals"],
        "skip_fields": set(),
        "notes": "Cloud Firewall DNS rules (requires DNS Control feature).",
    },
    "firewall_ips_rules": {
        "endpoint": "firewallIpsRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "ip_destination_groups", "ip_source_groups",
                       "locations", "location_groups", "time_intervals"],
        "skip_fields": set(),
        "notes": "Cloud Firewall IPS rules (requires IPS feature).",
    },
    "nat_control_rules": {
        "endpoint": "dnatRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "locations", "location_groups", "groups",
                       "departments", "time_intervals"],
        "skip_fields": set(),
        "notes": "Destination NAT rules (requires NAT Control feature).",
    },
    "ssl_inspection_rules": {
        "endpoint": "sslInspectionRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "url_categories", "groups", "departments",
                       "locations", "location_groups", "time_intervals"],
        "skip_fields": set(),
        "notes": "",
    },
    "sandbox_rules": {
        "endpoint": "sandboxRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "url_categories", "groups", "departments",
                       "locations", "location_groups", "time_intervals"],
        "skip_fields": set(),
        "notes": "Sandbox inspection rules (requires Sandbox feature).",
    },
    "bandwidth_control_rules": {
        "endpoint": "bandwidthControlRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "bandwidth_classes", "groups", "departments",
                       "locations", "location_groups", "time_intervals"],
        "skip_fields": set(),
        "notes": "",
    },
    "file_type_rules": {
        "endpoint": "fileTypeRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "custom_file_types", "url_categories",
                       "groups", "departments", "locations", "location_groups",
                       "time_intervals"],
        "skip_fields": set(),
        "notes": "",
    },
    "dlp_web_rules": {
        "endpoint": "webDlpRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "dlp_dictionaries", "dlp_engines",
                       "dlp_notification_templates", "url_categories",
                       "groups", "departments", "locations", "location_groups",
                       "time_intervals"],
        "skip_fields": set(),
        "notes": "",
    },
    "cloud_app_control_rules": {
        "endpoint": "webApplicationRules/SOCIAL_NETWORKING",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "groups", "departments",
                       "locations", "location_groups", "time_intervals"],
        "skip_fields": set(),
        "notes": "⚠ Cloud App Control covers multiple rule types (SOCIAL_NETWORKING, "
                 "STREAMING, etc.). Each type must be synced separately. "
                 "Currently only SOCIAL_NETWORKING is included as example — extend as needed.",
    },
    "casb_dlp_rules": {
        "endpoint": "casbDlpRules",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels", "dlp_dictionaries", "dlp_engines",
                       "dlp_notification_templates"],
        "skip_fields": set(),
        "notes": "CASB DLP rules (requires CASB feature/license).",
    },
    "casb_malware_rules": {
        "endpoint": "casbMalwareRules/all",  # /all returns all types; bare endpoint needs ruleType param
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": ["rule_labels"],
        "skip_fields": set(),
        "notes": "CASB Malware rules (requires CASB feature/license).",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # ADMIN
    # ══════════════════════════════════════════════════════════════════════════

    "admin_users": {
        "endpoint": "adminUsers",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "loginName",
        "depends_on": [],
        "skip_fields": {"password"},
        "sensitive": True,
        "notes": "⚠ SENSITIVE: Admin accounts with portal access. Synced only with explicit approval. Passwords NOT exported.",
    },
    "cloud_nss_feeds": {
        "endpoint": "nssFeeds",
        "kind": "list",
        "writable": True,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Cloud NSS (Nanolog Streaming Service) feed configurations.",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # SETTINGS — single object, GET + PUT (no id, no list)
    # ══════════════════════════════════════════════════════════════════════════

    "auth_settings": {
        "endpoint": "authSettings",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Authentication method settings. SSO/SAML config may reference external IdP — verify manually.",
    },
    "advanced_settings": {
        "endpoint": "advancedSettings",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "",
    },
    "security_policy": {
        "endpoint": "security",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Security policy allowlist/blocklist (basic).",
    },
    "security_policy_advanced": {
        "endpoint": "security/advanced",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Advanced security policy settings including custom blacklist URLs.",
    },
    "atp_settings": {
        "endpoint": "cyberThreatProtection/advancedThreatSettings",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Advanced Threat Protection global settings.",
    },
    "atp_exceptions": {
        "endpoint": "cyberThreatProtection/securityExceptions",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "ATP security exception URLs.",
    },
    "malware_policy": {
        "endpoint": "cyberThreatProtection/malwarePolicy",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Malware protection policy settings.",
    },
    "malware_settings": {
        "endpoint": "cyberThreatProtection/malwareSettings",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Malware scan settings (file types, protocols).",
    },
    "ftp_settings": {
        "endpoint": "ftpSettings",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "FTP Control settings.",
    },
    "browser_control_settings": {
        "endpoint": "browserControlSettings",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Browser control (allowed browsers) settings.",
    },
    "end_user_notification": {
        "endpoint": "eun",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "End user notification (block page) customization.",
    },
    "mobile_threat_settings": {
        "endpoint": "mobileAdvanceThreatSettings",
        "kind": "settings",
        "writable": True,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Mobile Advanced Threat Protection settings.",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # READ-ONLY — backed up for reference, cannot be written via API
    # ══════════════════════════════════════════════════════════════════════════

    "url_categories_predefined": {
        "endpoint": "urlCategories",
        "kind": "readonly",
        "writable": False,
        "id_field": "id",
        "name_field": "configuredName",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Predefined URL categories — managed by Zscaler cloud, cannot be created or deleted. "
                 "Custom URL overrides in these categories ARE synced via url_categories.",
    },
    "network_services_predefined": {
        "endpoint": "networkServices",
        "kind": "readonly",
        "writable": False,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Predefined network services — managed by Zscaler, cannot be modified.",
    },
    "admin_roles": {
        "endpoint": "adminRoles/lite",
        "kind": "readonly",
        "writable": False,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Admin roles — predefined by Zscaler. Custom admin roles must be manually recreated in target.",
    },
    "intermediate_certificates": {
        "endpoint": "intermediateCaCertificate",
        "kind": "readonly",
        "writable": False,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Intermediate CA certificates for SSL inspection. "
                 "Certificates and private keys cannot be exported via API. "
                 "Must be re-imported manually (Admin Portal → SSL Inspection → Intermediate CA).",
    },
    "dlp_resources_icap": {
        "endpoint": "icapServers",
        "kind": "readonly",
        "writable": False,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "ICAP servers — read-only reference. Must be manually configured in target tenant.",
    },
    "dlp_resources_idm": {
        "endpoint": "idmprofile",
        "kind": "readonly",
        "writable": False,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "IDM (Indexed Document Matching) profiles — read-only. "
                 "Must be re-indexed in target (requires uploading original documents).",
    },
    "dlp_edm_schemas": {
        "endpoint": "dlpExactDataMatchSchemas",
        "kind": "readonly",
        "writable": False,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "EDM (Exact Data Match) schemas — read-only. "
                 "Must be re-uploaded in target (requires original data source).",
    },
    "browser_isolation_profiles": {
        "endpoint": "browserIsolation/profiles",
        "kind": "readonly",
        "writable": False,
        "id_field": "id",
        "name_field": "name",
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Cloud Browser Isolation profiles — read-only (requires CBI license). "
                 "Profile settings must be manually recreated in target.",
    },
    "cloud_applications": {
        "endpoint": "cloudApplications/policy",
        "kind": "readonly",
        "writable": False,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Cloud application reference list — read-only, managed by Zscaler.",
    },
    "organization_information": {
        "endpoint": "orgInformation",
        "kind": "readonly",
        "writable": False,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Organization info (company name, contact) — read-only. Update in target via Admin Portal.",
    },
    "vips": {
        "endpoint": "vips",
        "kind": "readonly",
        "writable": False,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "Zscaler Virtual IP addresses — cloud-managed, read-only.",
    },
    "subscription": {
        "endpoint": "subscriptions",
        "kind": "readonly",
        "writable": False,
        "id_field": None,
        "name_field": None,
        "depends_on": [],
        "skip_fields": set(),
        "notes": "License/subscription info — read-only. Ensure target has equivalent feature licenses.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Derived lists
# ─────────────────────────────────────────────────────────────────────────────

# Ordered migration sequence (respects dependencies)
MIGRATION_ORDER = [
    # Infrastructure first
    "rule_labels",
    "departments",
    "groups",
    "time_intervals",
    "workload_groups",
    # URL
    "url_categories",
    # Network objects
    "ip_destination_groups",
    "ip_source_groups",
    "network_services",
    "network_service_groups",
    "network_application_groups",
    "bandwidth_classes",
    "custom_file_types",
    # DLP
    "dlp_dictionaries",
    "dlp_engines",
    "dlp_notification_templates",
    # Traffic forwarding
    "static_ips",
    "vpn_credentials",
    "pac_files",
    "zpa_gateways",
    "locations",
    "location_groups",
    "gre_tunnels",
    # Identity
    "users",
    "alert_subscriptions",
    # Settings (no deps)
    "auth_settings",
    "advanced_settings",
    "security_policy",
    "security_policy_advanced",
    "atp_settings",
    "atp_exceptions",
    "malware_policy",
    "malware_settings",
    "ftp_settings",
    "browser_control_settings",
    "end_user_notification",
    "mobile_threat_settings",
    # Forwarding before rules
    "forwarding_rules",
    # Policy rules (all depend on objects above)
    "url_filtering_rules",
    "firewall_rules",
    "firewall_dns_rules",
    "firewall_ips_rules",
    "nat_control_rules",
    "ssl_inspection_rules",
    "sandbox_rules",
    "bandwidth_control_rules",
    "file_type_rules",
    "dlp_web_rules",
    "cloud_app_control_rules",
    "casb_dlp_rules",
    "casb_malware_rules",
    # Admin last
    "cloud_nss_feeds",
    "admin_users",
]

WRITABLE_RESOURCES  = [k for k in MIGRATION_ORDER if RESOURCES[k]["writable"]]
SETTINGS_RESOURCES  = [k for k in MIGRATION_ORDER if RESOURCES[k].get("kind") == "settings"]
LIST_RESOURCES      = [k for k in MIGRATION_ORDER if RESOURCES[k].get("kind") == "list"]
READ_ONLY_RESOURCES = [k for k, v in RESOURCES.items() if not v["writable"]]
