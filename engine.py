"""
engine.py — Core sync logic: backup, diff, migrate. Called by sync.py.
"""
import json
import copy
import time
import base64
import hashlib
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import ui
from zia_client import ZIAClient
from resources import (RESOURCES, MIGRATION_ORDER, WRITABLE_RESOURCES,
                       READ_ONLY_RESOURCES, SETTINGS_RESOURCES, LIST_RESOURCES,
                       SLOW_READ_ONLY_RESOURCES, SYSTEM_FIELDS)


BACKUPS_DIR = Path(__file__).parent / "backups"


def _decode_bytes_payload(content: bytes) -> dict:
    """Return a JSON-serialisable representation of raw API response bytes."""
    result = {
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }

    if not content:
        result["content"] = None
        return result

    payload = BytesIO(content)
    if zipfile.is_zipfile(payload):
        payload.seek(0)
        entries = []
        with zipfile.ZipFile(payload) as zf:
            for info in zf.infolist():
                item_bytes = zf.read(info)
                entry = {
                    "filename": info.filename,
                    "size_bytes": info.file_size,
                    "compressed_size_bytes": info.compress_size,
                    "sha256": hashlib.sha256(item_bytes).hexdigest(),
                }
                decoded = _decode_bytes_payload(item_bytes)
                if "zip_entries" in decoded:
                    entry["zip_entries"] = decoded["zip_entries"]
                elif "json" in decoded:
                    entry["json"] = decoded["json"]
                elif "text" in decoded:
                    entry["text"] = decoded["text"]
                elif "base64" in decoded:
                    entry["base64"] = decoded["base64"]
                entries.append(entry)
        result["zip_entries"] = entries
        return result

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        result["base64"] = base64.b64encode(content).decode("ascii")
        return result

    try:
        result["json"] = json.loads(text)
    except json.JSONDecodeError:
        result["text"] = text
    return result


def _decode_raw_api_response(response: dict) -> dict:
    """Normalise raw API responses so they can be saved in backup JSON."""
    headers = response.get("headers", {})
    body = response.get("body") or b""
    decoded = _decode_bytes_payload(body)
    decoded.update({
        "status": response.get("status"),
        "content_type": headers.get("Content-Type") or headers.get("content-type"),
        "content_disposition": headers.get("Content-Disposition") or headers.get("content-disposition"),
    })
    return decoded


def _fetch_child_resource(client: ZIAClient, meta: dict, result: dict) -> list:
    """Fetch a report-only endpoint once for each item in another resource."""
    source_key = meta["source_resource"]
    source_items = result.get("resources", {}).get(source_key) or []
    if isinstance(source_items, dict):
        source_items = [source_items]
    if not isinstance(source_items, list):
        return []

    id_field = meta.get("source_id_field", "id")
    name_field = meta.get("name_field") or "name"
    endpoint_template = meta["endpoint_template"]
    children = []

    for item in source_items:
        if not isinstance(item, dict) or item.get(id_field) in (None, ""):
            continue
        source_id = item[id_field]
        endpoint = endpoint_template.format(id=source_id)
        child = {
            "source_id": source_id,
            "source_name": item.get(name_field) or item.get("name") or item.get("configuredName"),
            "endpoint": endpoint,
        }
        try:
            if meta.get("raw"):
                child["data"] = _decode_raw_api_response(client.get_raw(
                    endpoint,
                    headers=meta.get("headers", {}),
                ))
            else:
                child["data"] = client.get(endpoint)
        except Exception as exc:
            child["error"] = str(exc)
        children.append(child)
        time.sleep(0.2)

    return children


# ─────────────────────────────────────────────────────────────────────────────
# Backup
# ─────────────────────────────────────────────────────────────────────────────

def backup_tenant(client: ZIAClient, label: str, out_path: Path, include_slow_readonly: bool = False) -> dict:
    """Download all configured ZIA resources from a tenant and save them to JSON.

    Iterates through every resource defined in RESOURCES in order, using a 0.4s
    delay between requests to stay within ZIA's rate limits. Resources with kind
    "settings" or "readonly" without an id_field are fetched as single objects via
    get(); everything else is fetched with get_paginated(). If pagination returns
    nothing, the function falls back to a plain get() in case the endpoint returns
    a single object rather than a list. Resources with method="POST" are fetched
    with the configured request body; raw responses are decoded into JSON-safe
    metadata and extracted ZIP/JSON/text content where possible.

    Errors per resource are caught individually and stored in result["errors"] so
    that a single failed endpoint does not abort the entire backup.

    Args:
        client:   Authenticated ZIAClient for the tenant to back up.
        label:    Human-readable name shown in progress output and stored in the backup.
        out_path: File path where the JSON backup will be written (created if missing).

    Returns:
        The backup dict with keys 'meta', 'resources', and 'errors'.
    """
    ui.section(f"Backing up: {label}")
    all_keys = list(RESOURCES.keys())
    result = {
        "meta": {
            "label": label,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cloud": client.base,
        },
        "resources": {},
        "errors": {},
        "skipped": {},
    }

    for i, key in enumerate(all_keys, 1):
        meta = RESOURCES[key]
        ui.step(i, len(all_keys), key)
        if key in SLOW_READ_ONLY_RESOURCES and not include_slow_readonly:
            result["resources"][key] = None
            result["skipped"][key] = "Slow read-only inventory; enable it in the app if needed."
            ui.skip("slow read-only inventory disabled")
            continue
        if key in SLOW_READ_ONLY_RESOURCES:
            print()
            ui.info(f"{key} is read-only and can take several minutes on large tenants.")
            ui.info("If it repeats pages, pagination protection will stop it before rate-limit runaway.")
            ui.step(i, len(all_keys), key)
        time.sleep(0.4)  # avoid rate limiting (ZIA: 1-2 req/sec on some endpoints)
        try:
            kind = meta.get("kind", "list")
            method = meta.get("method", "GET").upper()
            if kind == "children":
                data = _fetch_child_resource(client, meta, result)
            elif method == "POST" and meta.get("raw"):
                data = _decode_raw_api_response(client.post_raw(
                    meta["endpoint"],
                    meta.get("body"),
                    headers=meta.get("headers", {}),
                ))
            elif method == "POST":
                data = client.post(meta["endpoint"], meta.get("body", {}))
            elif method != "GET":
                raise RuntimeError(f"Unsupported resource method: {method}")
            elif kind == "settings" or kind == "readonly" and not meta.get("id_field"):
                # Single-object endpoint
                data = client.get(meta["endpoint"])
            else:
                data = client.get_paginated(meta["endpoint"])
                if not data:
                    # Fallback: try as single object
                    data = client.get(meta["endpoint"])
            result["resources"][key] = data
            count = len(data) if isinstance(data, list) else (1 if data else 0)
            ui.done(count)
        except Exception as e:
            result["errors"][key] = str(e)
            result["resources"][key] = None
            ui.fail(str(e))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    ui.ok(f"Saved → {out_path.name}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Diff
# ─────────────────────────────────────────────────────────────────────────────

def _strip(obj: dict, extra: set = None) -> dict:
    """Return a copy of obj with system fields and resource-specific skip fields removed.

    Also normalises all values via _normalize() so lists are sorted consistently.
    This is the canonical representation used for diff comparisons.

    Args:
        obj:   The resource object dict as returned by the ZIA API.
        extra: Additional field names to exclude (from the resource's skip_fields config).
    """
    skip = SYSTEM_FIELDS | (extra or set())
    return {k: _normalize(v) for k, v in obj.items() if k not in skip}


def _normalize(val):
    """Recursively normalise a value so that equivalent objects compare as equal.

    The ZIA API often returns list fields (e.g. port ranges, user groups) in
    arbitrary order. Without normalisation, two identical configurations would
    produce spurious diffs. This function sorts lists of primitives directly and
    sorts lists of dicts by their canonical JSON representation.

    Dict values are recursed into but their key order is not changed (Python dicts
    preserve insertion order and json.dumps with sort_keys handles the comparison).
    """
    if isinstance(val, list):
        items = [_normalize(i) for i in val]
        try:
            # Sort lists of primitives
            return sorted(items)
        except TypeError:
            # Sort lists of dicts by their JSON representation
            return sorted(items, key=lambda x: json.dumps(x, sort_keys=True)
                          if isinstance(x, dict) else str(x))
    if isinstance(val, dict):
        return {k: _normalize(v) for k, v in val.items()}
    return val


def _norm_name(obj: dict, name_field: str) -> str:
    """Return the normalised name of an object for use as a dict key.

    Strips whitespace and lowercases so that 'My Rule' and 'my rule' are
    treated as the same object during diff matching.
    """
    return str(obj.get(name_field, "")).strip().lower()


def diff_resource(key: str, src_items, tgt_items) -> dict:
    """Compute the diff between source and target for a list-type resource.

    Matches objects by their normalised name (case-insensitive, stripped).
    Objects present in source but not in target go into to_create.
    Objects present in both but with differing (stripped) fields go into to_update,
    with a 'changes' dict showing each field's old (target) and new (source) value.
    Objects present in target but not in source go into to_delete.

    Args:
        key:       Resource key from RESOURCES, used to look up metadata.
        src_items: List of dicts from the source backup (or None/non-list → treated as empty).
        tgt_items: List of dicts from the target backup (or None/non-list → treated as empty).

    Returns:
        Dict with keys: to_create, to_update, to_delete, unchanged (lists).
    """
    meta = RESOURCES[key]
    name_field = meta["name_field"]

    if not isinstance(src_items, list):
        src_items = []
    if not isinstance(tgt_items, list):
        tgt_items = []

    src_by = {_norm_name(i, name_field): i for i in src_items}
    tgt_by = {_norm_name(i, name_field): i for i in tgt_items}

    to_create, to_update, to_delete, unchanged = [], [], [], []

    for name, src in src_by.items():
        if name not in tgt_by:
            to_create.append(src)
        else:
            tgt = tgt_by[name]
            if _strip(src, meta.get("skip_fields")) != _strip(tgt, meta.get("skip_fields")):
                changes = {}
                for k in set(_strip(src)) | set(_strip(tgt)):
                    sv, tv = src.get(k), tgt.get(k)
                    if sv != tv:
                        changes[k] = {"from": tv, "to": sv}
                to_update.append({"source": src, "target": tgt, "changes": changes})
            else:
                unchanged.append(name)

    for name in tgt_by:
        if name not in src_by:
            to_delete.append(tgt_by[name])

    return {"to_create": to_create, "to_update": to_update,
            "to_delete": to_delete, "unchanged": unchanged}


def diff_settings(key: str, src: dict | None, tgt: dict | None) -> dict:
    """Compute the diff between source and target for a settings-type resource.

    Settings resources are single objects (no list, no ID). Instead of create/delete
    semantics, this produces a field-level 'changes' dict showing each field that
    differs between source and target.

    Special cases:
      - src is None → no source data (backup failed), returns empty changes.
      - tgt is None → target has never been configured, all source fields are "new".

    Args:
        key: Resource key (unused currently, kept for API symmetry with diff_resource).
        src: Source settings object dict, or None.
        tgt: Target settings object dict, or None.

    Returns:
        Dict with keys: changes (field → {from, to}), src, tgt.
    """
    if not src:
        return {"changes": {}, "src": None, "tgt": tgt}
    if not tgt:
        return {"changes": {k: {"from": None, "to": v} for k, v in _strip(src).items()},
                "src": src, "tgt": None}
    changes = {}
    for k in set(_strip(src)) | set(_strip(tgt)):
        sv, tv = src.get(k), tgt.get(k)
        if sv != tv:
            changes[k] = {"from": tv, "to": sv}
    return {"changes": changes, "src": src, "tgt": tgt}


def compute_diff(src_backup: dict, tgt_backup: dict) -> dict:
    """Compare two tenant backups and produce a full diff structure.

    Iterates over all WRITABLE_RESOURCES, dispatching to diff_settings() or
    diff_resource() based on each resource's kind. Also collects READ_ONLY_RESOURCES
    into a separate section for the report (no changes applied for those).

    Resources where the target backup itself failed (listed in tgt_backup["errors"])
    are marked as skipped rather than treated as empty — this prevents falsely
    creating all source objects in the target when the backup simply timed out.

    Args:
        src_backup: Backup dict for the source tenant (from backup_tenant()).
        tgt_backup: Backup dict for the target tenant (from backup_tenant()),
                    or a minimal stub {'meta': {}, 'resources': {}} for a blank target.

    Returns:
        Diff dict with keys: meta, writable (per-resource diffs), read_only, summary.
    """
    result = {
        "meta": {
            "source_label": src_backup.get("meta", {}).get("label", "Source"),
            "target_label": tgt_backup.get("meta", {}).get("label", "Target"),
            "source_timestamp": src_backup.get("meta", {}).get("timestamp"),
            "target_timestamp": tgt_backup.get("meta", {}).get("timestamp"),
            "generated": datetime.now(timezone.utc).isoformat(),
        },
        "writable": {},
        "read_only": {},
        "summary": {},
    }

    src_res = src_backup.get("resources", {})
    tgt_res = tgt_backup.get("resources", {})

    for key in WRITABLE_RESOURCES:
        meta = RESOURCES[key]
        kind = meta.get("kind", "list")
        src_data = src_res.get(key)
        tgt_data = tgt_res.get(key)

        if kind == "settings":
            # Skip if either side failed to back up
            if src_data is None or tgt_data is None:
                result["writable"][key] = {"changes": {}, "skipped": True}
                result["summary"][key] = {"create": 0, "update": 0, "delete": 0, "unchanged": 0}
                continue
            d = diff_settings(key, src_data, tgt_data)
            result["writable"][key] = d
            chg = bool(d.get("changes"))
            result["summary"][key] = {
                "create": 0, "update": 1 if chg else 0,
                "delete": 0, "unchanged": 0 if chg else 1,
            }
        else:
            # If target backup failed (None), skip — don't treat as empty
            if tgt_data is None and key in tgt_backup.get("errors", {}):
                result["writable"][key] = {
                    "to_create": [], "to_update": [], "to_delete": [],
                    "unchanged": [], "skipped": True,
                }
                result["summary"][key] = {"create": 0, "update": 0, "delete": 0, "unchanged": 0}
                continue
            d = diff_resource(key, src_data, tgt_data)
            result["writable"][key] = d
            result["summary"][key] = {
                "create": len(d["to_create"]),
                "update": len(d["to_update"]),
                "delete": len(d["to_delete"]),
                "unchanged": len(d["unchanged"]),
            }

    for key in READ_ONLY_RESOURCES:
        src_data = src_res.get(key)
        result["read_only"][key] = {
            "note": RESOURCES[key]["notes"],
            "source_count": len(src_data) if isinstance(src_data, list) else (1 if src_data else 0),
        }

    return result


def has_changes(diff: dict) -> bool:
    """Return True if the diff contains at least one create, update, or delete operation."""
    for s in diff.get("summary", {}).values():
        if s["create"] or s["update"] or s["delete"]:
            return True
    return False


def print_diff_summary(diff: dict):
    """Print a compact colour-coded summary of all pending changes to the terminal.

    Only resources with at least one create (+), update (~), or delete (-) are shown.
    Uses MIGRATION_ORDER so resources are listed in the same order they will be applied.
    """
    ui.section("Changes detected")
    summary = diff.get("summary", {})
    any_changes = False
    for key in MIGRATION_ORDER:
        s = summary.get(key, {})
        c, u, d = s.get("create", 0), s.get("update", 0), s.get("delete", 0)
        if c or u or d:
            any_changes = True
            parts = []
            if c: parts.append(ui._c(ui.GRN, f"+{c}"))
            if u: parts.append(ui._c(ui.YLW, f"~{u}"))
            if d: parts.append(ui._c(ui.RED,  f"-{d}"))
            print(f"    {key:<35} {' '.join(parts)}")

    if not any_changes:
        ui.ok("Tenants are already in sync — no changes needed.")


# ─────────────────────────────────────────────────────────────────────────────
# ID Mapper
# ─────────────────────────────────────────────────────────────────────────────

class IDMapper:
    """Maps source object IDs to their corresponding target IDs.

    When migrating between tenants, every object gets a new ID in the target.
    Rules and groups reference their dependencies by ID, so before creating or
    updating an object in the target, all nested ID references must be remapped
    from source IDs to target IDs.

    The mapper is populated in two ways:
      1. seed_from_existing(): at the start of each resource, match source and
         target objects by name and record their ID pairs.
      2. add(): after a successful POST, record the new target ID returned by the API.

    remap() is then called on every object body before it is sent to the target.
    """

    def __init__(self):
        """Initialise with an empty mapping store."""
        self._map: dict[str, dict[str, str]] = {}

    def add(self, resource_key: str, src_id: str, tgt_id: str):
        """Record a source→target ID pair for a specific resource type.

        Args:
            resource_key: Resource key (e.g. 'groups') — used to organise the map.
            src_id:       ID of the object in the source tenant.
            tgt_id:       ID of the corresponding object in the target tenant.
        """
        self._map.setdefault(resource_key, {})[str(src_id)] = str(tgt_id)

    def remap(self, obj: dict) -> dict:
        """Return a deep copy of obj with all known source IDs replaced by target IDs.

        Only remaps 'id' keys inside nested objects (not the root object's own 'id',
        which must be set explicitly by the caller to the target's ID).
        """
        return self._walk(copy.deepcopy(obj))

    def _walk(self, val):
        """Recursively traverse a value and remap any 'id' fields found in dicts."""
        if isinstance(val, list):
            return [self._walk(i) for i in val]
        if not isinstance(val, dict):
            return val
        out = {}
        for k, v in val.items():
            if k == "id" and isinstance(v, (str, int)):
                # Only remap nested object IDs (not the root object's own id)
                remapped = self._lookup(str(v))
                out[k] = remapped if remapped else v
            else:
                out[k] = self._walk(v)
        return out

    def _lookup(self, sid: str) -> str | None:
        """Search all resource mappings for a given source ID.

        Returns the target ID string if found, or None if the ID is unknown
        (e.g. a predefined/system object whose ID is the same in both tenants).
        """
        for mapping in self._map.values():
            if sid in mapping:
                return mapping[sid]
        return None

    def seed_from_existing(self, resource_key: str, src_items: list,
                            tgt_items_by_name: dict, name_field: str):
        """Pre-populate the mapper by matching source and target objects by name.

        Called at the start of each resource section so that objects that already
        exist in the target (from a previous sync or pre-existing config) have their
        ID pairs registered before any create/update operations run. This ensures
        that rules referencing these objects get the correct target IDs.

        Args:
            resource_key:       Resource key used to store the mapping.
            src_items:          List of source objects from the backup.
            tgt_items_by_name:  Dict of normalised_name → target object, from _get_existing().
            name_field:         The field name used as the human-readable identifier.
        """
        for src in src_items:
            name = _norm_name(src, name_field)
            tgt = tgt_items_by_name.get(name)
            if tgt and src.get("id") and tgt.get("id"):
                self.add(resource_key, str(src["id"]), str(tgt["id"]))


# ─────────────────────────────────────────────────────────────────────────────
# Migrate
# ─────────────────────────────────────────────────────────────────────────────

def _clean(obj: dict, meta: dict) -> dict:
    """Remove fields that must not be sent in POST/PUT request bodies.

    Strips SYSTEM_FIELDS (id, creationTime, etc. — the API rejects these on write)
    and any resource-specific skip_fields (e.g. preSharedKey for VPN credentials,
    password for users). Unlike _strip(), this does NOT normalise values — it
    preserves the original data for sending to the API.

    Args:
        obj:  Resource object dict from the source backup.
        meta: Resource metadata entry from RESOURCES.
    """
    skip = SYSTEM_FIELDS | meta.get("skip_fields", set())
    return {k: v for k, v in obj.items() if k not in skip}


def _get_existing(client: ZIAClient, key: str) -> dict:
    """Fetch the current objects in the target tenant and return them keyed by normalised name.

    Used to seed the IDMapper before processing each resource — we need to know
    which objects already exist in the target and what IDs they have been assigned.

    Returns an empty dict on any error (e.g. the target has no objects yet, or the
    endpoint returns a non-list response).

    Args:
        client: Authenticated ZIAClient for the target tenant.
        key:    Resource key from RESOURCES.
    """
    meta = RESOURCES[key]
    try:
        items = client.get_paginated(meta["endpoint"])
        if items and isinstance(items, list) and meta["name_field"]:
            return {_norm_name(i, meta["name_field"]): i for i in items}
    except Exception:
        pass
    return {}


def apply_diff(client: ZIAClient, diff: dict, src_backup: dict,
               dry_run: bool = False, no_delete: bool = False,
               sync_sensitive: bool = False) -> dict:
    """Apply (or simulate) all changes in a diff to the target tenant.

    Processes resources in MIGRATION_ORDER to respect dependency ordering.
    For each resource:
      1. Checks the sensitive gate — skips the resource if it is marked sensitive
         and sync_sensitive is False.
      2. For settings-type resources: PUTs the full source object if there are changes.
      3. For list-type resources:
         a. Seeds the IDMapper with already-matching objects in the target.
         b. CREATEs all new objects (POST), recording new target IDs in the mapper.
         c. UPDATEs changed objects (PUT), skipping system-defined/predefined items.
         d. DELETEs removed objects (DELETE), unless no_delete is True or system-defined.

    In dry_run mode, all operations are logged as 'dry' instead of being sent to the API.

    Args:
        client:         Authenticated ZIAClient for the target tenant.
        diff:           Diff dict produced by compute_diff().
        src_backup:     Source backup dict — used to re-fetch the full source objects
                        (the diff only stores changed fields for updates).
        dry_run:        If True, simulate all operations without calling the API.
        no_delete:      If True, skip all delete operations (safe mode).
        sync_sensitive: If False (default), skip resources marked sensitive=True
                        (groups, users, admin_users).

    Returns:
        Result dict with keys: ok (int), errors (int), skipped (int), dry (int),
        error_details (list of failed operations), log (full operation list).
    """

    id_mapper = IDMapper()
    log = []
    errors = []

    def record(action, key, name, status, detail=""):
        log.append({"action": action, "resource": key, "name": name,
                     "status": status, "detail": detail})
        icon = ui._c(ui.GRN, "✓") if status == "ok" else \
               ui._c(ui.YLW, "~") if status in ("dry", "skip") else \
               ui._c(ui.RED, "✗")
        action_str = ui._c(ui.BLU, f"{action:7}")
        print(f"    {icon} {action_str} {key}/{name[:40]:<42} {ui._c(ui.DIM, detail[:50])}")
        if status == "error":
            errors.append({"action": action, "resource": key, "name": name, "error": detail})

    writable_diff = diff.get("writable", {})
    src_res = src_backup.get("resources", {})

    for key in MIGRATION_ORDER:
        if key not in writable_diff:
            continue
        meta = RESOURCES[key]
        kind = meta.get("kind", "list")
        d = writable_diff[key]

        # ── Sensitive resources gate ───────────────────────────────────────
        if meta.get("sensitive") and not sync_sensitive:
            record("SKIP", key, key, "skip", "sensitive — not enabled in config")
            continue

        # ── Settings object (GET + PUT, no list) ──────────────────────────
        if kind == "settings":
            if not d.get("changes"):
                continue
            ui.section(key)
            src_obj = d.get("src")
            if not src_obj:
                continue
            endpoint = meta["endpoint"].split("?")[0]
            body = _clean(src_obj, meta)
            name = endpoint
            if dry_run:
                record("UPDATE", key, name, "dry",
                       ", ".join(list(d["changes"].keys())[:5]))
            else:
                try:
                    client.put(endpoint, body)
                    record("UPDATE", key, name, "ok",
                           ", ".join(list(d["changes"].keys())[:5]))
                except Exception as e:
                    record("UPDATE", key, name, "error", str(e)[:100])
            continue

        creates = d.get("to_create", [])
        updates = d.get("to_update", [])
        deletes = d.get("to_delete", []) if not no_delete else []

        if not creates and not updates and not deletes:
            continue

        ui.section(key)

        # Seed ID mapper with already-matching objects
        existing = _get_existing(client, key)
        src_items = src_res.get(key) or []
        if isinstance(src_items, list):
            id_mapper.seed_from_existing(key, src_items, existing, meta["name_field"])

        endpoint = meta["endpoint"].split("?")[0]
        name_field = meta["name_field"]

        for obj in creates:
            name = str(obj.get(name_field, obj.get("id", "?")))
            body = _clean(obj, meta)
            body = id_mapper.remap(body)
            if dry_run:
                record("CREATE", key, name, "dry")
                continue
            try:
                result = client.post(endpoint, body)
                if result and meta.get("id_field") and "id" in result:
                    id_mapper.add(key, str(obj.get("id", "")), str(result["id"]))
                record("CREATE", key, name, "ok")
            except Exception as e:
                record("CREATE", key, name, "error", str(e)[:100])

        for change in updates:
            src, tgt = change["source"], change["target"]
            name = str(src.get(name_field, src.get("id", "?")))
            tgt_id = tgt.get(meta.get("id_field", "id"))
            if tgt.get("isSystemDefined") or tgt.get("predefined"):
                record("UPDATE", key, name, "skip", "system-defined")
                continue
            body = _clean(src, meta)
            body[meta.get("id_field", "id")] = tgt_id
            body = id_mapper.remap(body)
            if dry_run:
                record("UPDATE", key, name, "dry",
                       ", ".join(list(change.get("changes", {}).keys())[:5]))
                continue
            try:
                client.put(f"{endpoint}/{tgt_id}", body)
                id_mapper.add(key, str(src.get("id", "")), str(tgt_id))
                record("UPDATE", key, name, "ok",
                       ", ".join(list(change.get("changes", {}).keys())[:5]))
            except Exception as e:
                record("UPDATE", key, name, "error", str(e)[:100])

        for obj in deletes:
            name = str(obj.get(name_field, obj.get("id", "?")))
            tgt_id = obj.get(meta.get("id_field", "id"))
            if obj.get("isSystemDefined") or obj.get("predefined"):
                record("DELETE", key, name, "skip", "system-defined")
                continue
            if dry_run:
                record("DELETE", key, name, "dry")
                continue
            try:
                client.delete(f"{endpoint}/{tgt_id}")
                record("DELETE", key, name, "ok")
            except Exception as e:
                record("DELETE", key, name, "error", str(e)[:100])

    ok_count    = sum(1 for e in log if e["status"] == "ok")
    error_count = sum(1 for e in log if e["status"] == "error")
    skip_count  = sum(1 for e in log if e["status"] == "skip")
    dry_count   = sum(1 for e in log if e["status"] == "dry")

    return {
        "ok": ok_count,
        "errors": error_count,
        "skipped": skip_count,
        "dry": dry_count,
        "error_details": errors,
        "log": log,
    }
