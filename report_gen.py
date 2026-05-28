"""
report_gen.py — HTML report generators.
"""
import json
import re
import html as html_lib
from datetime import datetime, timezone
from pathlib import Path
from resources import RESOURCES, WRITABLE_RESOURCES, READ_ONLY_RESOURCES, MIGRATION_ORDER

CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     background:#0d1117;color:#c9d1d9;margin:0;padding:24px;line-height:1.5}
h1{color:#58a6ff;border-bottom:1px solid #21262d;padding-bottom:12px}
h2{color:#79c0ff;margin-top:32px}h3{color:#a8d8a8}
a{color:#58a6ff}
.card{background:#161b22;border:1px solid #21262d;border-radius:8px;
      padding:16px;margin:12px 0}
table{border-collapse:collapse;width:100%;margin:8px 0}
th{background:#21262d;color:#79c0ff;text-align:left;padding:8px 12px;
   font-size:.85em;font-weight:600}
td{border-bottom:1px solid #21262d;padding:7px 12px;font-size:.85em}
tr:hover td{background:#1c2128}
.badge{display:inline-block;padding:1px 8px;border-radius:12px;
       font-size:.78em;font-weight:600;margin:1px}
.c{background:#0d3e1e;color:#56d364}.u{background:#3d2b00;color:#e3b341}
.d{background:#3d0000;color:#f85149}.ok{background:#0d2748;color:#79c0ff}
.ro{background:#1c2128;color:#8b949e}.zero{color:#484f58}
.warn{color:#e3b341}.err{color:#f85149}
.meta{color:#8b949e;font-size:.82em}
pre{background:#0d1117;border:1px solid #21262d;border-radius:4px;
    padding:12px;overflow-x:auto;font-size:.82em;color:#a8d8a8}
details.resource{background:#161b22;border:1px solid #21262d;border-radius:8px;
      margin:12px 0}
details.resource>summary{cursor:pointer;list-style:none;padding:14px 16px;
      font-weight:700;color:#79c0ff}
details.resource>summary::-webkit-details-marker{display:none}
.resource-body{border-top:1px solid #21262d;padding:0 16px 16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.stat{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:12px}
.stat strong{display:block;color:#f0f6fc;font-size:1.4em}
.nav a{display:inline-block;margin:2px 6px 2px 0}
.pill{display:inline-block;border:1px solid #30363d;border-radius:12px;
      padding:1px 8px;margin:1px 3px 1px 0;color:#8b949e;font-size:.78em}
.json{white-space:pre-wrap;word-break:break-word}
.redacted{color:#e3b341;font-style:italic}
.errbox{border:1px solid #8b3a3a;background:#2d1117;color:#f85149;
        border-radius:6px;padding:10px;margin:10px 0}
"""

SECRET_FIELD_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "privatekey",
    "presharedkey",
    "passphrase",
)


def _esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or "item"


def _is_sensitive_field(field_name: str) -> bool:
    normalised = re.sub(r"[^a-z0-9]+", "", field_name.lower())
    return any(marker in normalised for marker in SECRET_FIELD_MARKERS)


def _redact(value, field_name: str = ""):
    if field_name and _is_sensitive_field(field_name):
        return "<redacted>"
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, field_name) for item in value]
    return value


def _safe_json(value, field_name: str = "") -> str:
    safe = _redact(value, field_name)
    text = json.dumps(safe, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    return f'<pre class="json">{_esc(text)}</pre>'


def _count(data) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return 1 if data else 0
    return 1 if data is not None else 0


def _scalar(value) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar_text(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def _preview(value, field_name: str = "", limit: int = 180) -> str:
    safe = _redact(value, field_name)
    if _scalar(safe):
        text = _scalar_text(safe)
    else:
        text = json.dumps(safe, sort_keys=True, ensure_ascii=False, default=str)
    if len(text) > limit:
        text = text[:limit - 1] + "..."
    css = "redacted" if text == "<redacted>" else "meta"
    return f'<span class="{css}">{_esc(text)}</span>'


def _display_name(resource_key: str, obj: dict) -> str:
    meta = RESOURCES.get(resource_key, {})
    for field in (meta.get("name_field"), "name", "configuredName",
                  "loginName", "email", "id"):
        if field and obj.get(field) not in (None, ""):
            return str(obj[field])
    return "unnamed"


def _choose_columns(resource_key: str, items: list[dict]) -> list[str]:
    meta = RESOURCES.get(resource_key, {})
    preferred = [
        meta.get("name_field"),
        meta.get("id_field"),
        "enabled",
        "state",
        "status",
        "type",
        "order",
        "rank",
        "action",
        "description",
    ]
    columns = []
    for field in preferred:
        if (field and field not in columns and
                any(isinstance(item, dict) and field in item for item in items[:20])):
            columns.append(field)

    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        for field, value in item.items():
            if field not in columns and not _is_sensitive_field(field) and _scalar(value):
                columns.append(field)
            if len(columns) >= 8:
                return columns
    return columns[:8]


def _render_object_table(obj: dict) -> str:
    if not obj:
        return '<p class="meta">Empty object returned.</p>'
    rows = []
    for key in sorted(obj):
        value = obj[key]
        if _scalar(value) or _is_sensitive_field(key):
            rendered = _preview(value, key, 500)
        else:
            rendered = _safe_json(value, key)
        rows.append(f"<tr><td><strong>{_esc(key)}</strong></td><td>{rendered}</td></tr>")
    return "<table><tr><th>Field</th><th>Value</th></tr>" + "".join(rows) + "</table>"


def _render_list(resource_key: str, items: list) -> str:
    if not items:
        return '<p class="meta">No items returned.</p>'

    if not all(isinstance(item, dict) for item in items):
        rows = [
            f"<tr><td>{idx}</td><td>{_preview(item, limit=500)}</td></tr>"
            for idx, item in enumerate(items, 1)
        ]
        return "<table><tr><th>#</th><th>Value</th></tr>" + "".join(rows) + "</table>"

    columns = _choose_columns(resource_key, items)
    header_cells = "".join(f"<th>{_esc(col)}</th>" for col in columns)
    rows = []
    for idx, item in enumerate(items, 1):
        cells = [f"<td>{idx}</td>"]
        for col in columns:
            cells.append(f"<td>{_preview(item.get(col), col)}</td>")
        name = _esc(_display_name(resource_key, item))
        cells.append(
            "<td><details>"
            f"<summary>{name}</summary>{_safe_json(item)}"
            "</details></td>"
        )
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<table><tr><th>#</th>"
        f"{header_cells}<th>Full API object</th></tr>"
        + "".join(rows) +
        "</table>"
    )


def _render_resource_section(tenant_idx: int, resource_key: str,
                             backup: dict) -> str:
    meta = RESOURCES[resource_key]
    data = backup.get("resources", {}).get(resource_key)
    errors = backup.get("errors", {})
    section_id = f"tenant-{tenant_idx}-{_slug(resource_key)}"
    count = _count(data)
    kind = meta.get("kind", "list")
    writable = "writable" if meta.get("writable") else "read-only"
    open_attr = " open" if resource_key in errors else ""

    parts = [
        f'<details class="resource" id="{section_id}"{open_attr}>',
        "<summary>",
        f"{_esc(resource_key)} "
        f'<span class="badge {"d" if resource_key in errors else "ok"}">{count} item(s)</span>',
        f'<span class="pill">{_esc(kind)}</span>',
        f'<span class="pill">{_esc(writable)}</span>',
        "</summary>",
        '<div class="resource-body">',
        f'<p class="meta">Endpoint: <code>{_esc(meta.get("method", "GET"))} {_esc(meta.get("endpoint", ""))}</code></p>',
    ]
    if meta.get("notes"):
        parts.append(f'<p class="warn meta">{_esc(meta["notes"])}</p>')
    if resource_key in errors:
        parts.append(f'<div class="errbox">{_esc(errors[resource_key])}</div>')

    if isinstance(data, list):
        parts.append(_render_list(resource_key, data))
    elif isinstance(data, dict):
        parts.append(_render_object_table(data))
        parts.append("<details><summary>Raw API object</summary>")
        parts.append(_safe_json(data))
        parts.append("</details>")
    elif data is None:
        parts.append('<p class="meta">No data was returned for this endpoint.</p>')
    else:
        parts.append(_preview(data, limit=1000))

    parts.append("</div></details>")
    return "\n".join(parts)


def badge(text, cls):
    """Return an HTML badge span with the given CSS class.

    Predefined classes (from CSS): c=create (green), u=update (yellow),
    d=delete (red), ok=applied (blue), ro=read-only (grey).
    """
    return f'<span class="badge {cls}">{text}</span>'


def gen_report(diff: dict, src_backup: dict, result: dict | None,
               out_path: Path):
    """Generate a self-contained HTML report and write it to out_path.

    The report includes:
      - A header with source/target labels and backup timestamps.
      - A summary table showing create/update/delete/unchanged counts per resource.
      - Per-resource change detail sections (names and changed fields), capped at
        30 items per section to keep the file manageable.
      - A migration result section (if result is provided) showing applied/error counts
        and a table of any failed operations.
      - A read-only resources table listing items that need manual attention.
      - The full MIGRATION_ORDER list for reference.

    Args:
        diff:      Diff dict from compute_diff().
        src_backup: Source backup dict (currently unused in HTML generation, kept
                    for API symmetry — may be used in future for full object details).
        result:    Result dict from apply_diff(), or None if no changes were applied
                   (e.g. dry-run was cancelled, or tenants were already in sync).
        out_path:  File path to write the HTML report to.

    Returns:
        The out_path Path object (for chaining / display to the user).
    """

    src_label = diff.get("meta", {}).get("source_label", "Source")
    tgt_label = diff.get("meta", {}).get("target_label", "Target")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    src_ts = (diff.get("meta", {}).get("source_timestamp") or "?")[:19].replace("T", " ")
    tgt_ts = (diff.get("meta", {}).get("target_timestamp") or "not yet backed up")[:19].replace("T", " ")

    # Summary table
    summary_rows = []
    total_c = total_u = total_d = 0
    for key in WRITABLE_RESOURCES:
        s = diff.get("summary", {}).get(key, {})
        c, u, d, eq = s.get("create",0), s.get("update",0), s.get("delete",0), s.get("unchanged",0)
        total_c += c; total_u += u; total_d += d
        row = f"""<tr>
          <td><strong>{key}</strong></td>
          <td>{"<span class='zero'>0</span>" if not c else badge(f"+{c}","c")}</td>
          <td>{"<span class='zero'>0</span>" if not u else badge(f"~{u}","u")}</td>
          <td>{"<span class='zero'>0</span>" if not d else badge(f"-{d}","d")}</td>
          <td class="zero">{eq}</td>
        </tr>"""
        summary_rows.append(row)

    # Change details
    change_sections = []
    for key in MIGRATION_ORDER:
        d_data = diff.get("writable", {}).get(key, {})
        creates = d_data.get("to_create", [])
        updates = d_data.get("to_update", [])
        deletes = d_data.get("to_delete", [])
        if not creates and not updates and not deletes:
            continue
        meta = RESOURCES.get(key, {})
        nf = meta.get("name_field", "name")
        notes = meta.get("notes", "")
        section_html = [f'<div class="card"><h3>{key}</h3>']
        if notes:
            section_html.append(f'<p class="warn meta">⚠ {notes}</p>')
        if creates:
            section_html.append(f'<p>{badge(f"+{len(creates)} to create","c")}</p>')
            section_html.append('<table><tr><th>Name</th><th>Preview</th></tr>')
            for obj in creates[:30]:
                name = obj.get(nf, obj.get("id","?"))
                preview = "; ".join(f"{k}={v}" for k,v in list(obj.items())[:4]
                                     if k not in {nf,"id"} and not isinstance(v,(dict,list)))
                section_html.append(f'<tr><td>{name}</td><td class="meta">{preview[:120]}</td></tr>')
            if len(creates) > 30:
                section_html.append(f'<tr><td colspan="2" class="meta">… and {len(creates)-30} more</td></tr>')
            section_html.append('</table>')
        if updates:
            section_html.append(f'<p>{badge(f"~{len(updates)} to update","u")}</p>')
            section_html.append('<table><tr><th>Name</th><th>Changed fields</th></tr>')
            for ch in updates[:30]:
                name = ch["source"].get(nf, ch["source"].get("id","?"))
                fields = ", ".join(ch.get("changes",{}).keys())
                section_html.append(f'<tr><td>{name}</td><td class="meta">{fields[:120]}</td></tr>')
            if len(updates) > 30:
                section_html.append(f'<tr><td colspan="2" class="meta">… and {len(updates)-30} more</td></tr>')
            section_html.append('</table>')
        if deletes:
            section_html.append(f'<p>{badge(f"-{len(deletes)} to delete","d")}</p>')
            section_html.append('<table><tr><th>Name</th></tr>')
            for obj in deletes[:30]:
                name = obj.get(nf, obj.get("id","?"))
                section_html.append(f'<tr><td>{name}</td></tr>')
            if len(deletes) > 30:
                section_html.append(f'<tr><td colspan="2" class="meta">… and {len(deletes)-30} more</td></tr>')
            section_html.append('</table>')
        section_html.append('</div>')
        change_sections.append("\n".join(section_html))

    # Read-only table
    ro_rows = []
    for key in READ_ONLY_RESOURCES:
        d_ro = diff.get("read_only", {}).get(key, {})
        note = RESOURCES[key]["notes"]
        count = d_ro.get("source_count", 0)
        ro_rows.append(f'<tr><td>{badge("READ-ONLY","ro")} <strong>{key}</strong></td>'
                        f'<td>{count}</td><td class="meta">{note}</td></tr>')

    # Migration result (if provided)
    result_html = ""
    if result:
        status_color = "c" if result["errors"] == 0 else "d"
        result_html = f"""
<h2>Last Migration Result</h2>
<div class="card">
  <p>{badge(f"Applied: {result['ok']}","ok")}
     {badge(f"Errors: {result['errors']}","d") if result['errors'] else ""}
     {badge(f"Skipped: {result['skipped']}","ro")}
     {badge(f"Dry-run: {result['dry']}","u") if result.get('dry') else ""}
  </p>
  {"" if not result.get("error_details") else
  '<table><tr><th>Action</th><th>Resource</th><th>Name</th><th>Error</th></tr>' +
  "".join(f'<tr><td>{e["action"]}</td><td>{e["resource"]}</td><td>{e["name"]}</td>'
          f'<td class="err meta">{e["error"][:100]}</td></tr>'
          for e in result["error_details"]) +
  '</table>'}
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<title>ZIA Sync Report — {src_label} → {tgt_label}</title>
<style>{CSS}</style>
</head>
<body>
<h1>ZIA Sync Report</h1>
<p class="meta">Generated: {generated} &nbsp;|&nbsp;
   Source ({src_label}): {src_ts} &nbsp;|&nbsp;
   Target ({tgt_label}): {tgt_ts}</p>

<h2>Summary</h2>
<div class="card">
  <p class="meta">Total changes: {badge(f"+{total_c}","c")} {badge(f"~{total_u}","u")} {badge(f"-{total_d}","d")}</p>
  <table>
    <tr><th>Resource</th><th>Create</th><th>Update</th><th>Delete</th><th>Unchanged</th></tr>
    {"".join(summary_rows)}
  </table>
</div>

{result_html}

<h2>Change Details</h2>
{"".join(change_sections) if change_sections else '<div class="card"><p>No changes detected — tenants are in sync.</p></div>'}

<h2>Read-Only Settings — Manual Action Required</h2>
<div class="card">
<p class="meta">These settings cannot be migrated via API and must be configured manually in the target tenant.</p>
<table>
  <tr><th>Resource</th><th>Items in Source</th><th>Notes</th></tr>
  {"".join(ro_rows)}
</table>
</div>

<h2>Migration Order</h2>
<div class="card">
<pre>{"".join(f'{i+1:2}. {k}' + chr(10) for i,k in enumerate(MIGRATION_ORDER))}</pre>
</div>
</body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def gen_full_report(backups: list[dict] | dict, out_path: Path):
    """Generate a full HTML inventory report from one or more tenant backups.

    Unlike gen_report(), this is not a diff report. It renders every resource and
    settings object present in the supplied backup data, including read-only
    endpoints. Secret-looking fields are redacted in the HTML output only; the
    underlying backup JSON files remain unchanged.
    """
    if isinstance(backups, dict):
        backups = [backups]

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    asset_dir = out_path.with_name(f"{out_path.stem}_files")
    asset_dir.mkdir(parents=True, exist_ok=True)
    tenant_sections = []
    tenant_nav = []
    overview_rows = []

    for tenant_idx, backup in enumerate(backups, 1):
        meta = backup.get("meta", {})
        label = meta.get("label") or f"Tenant {tenant_idx}"
        timestamp = (meta.get("timestamp") or "?")[:19].replace("T", " ")
        cloud = meta.get("cloud") or "?"
        errors = backup.get("errors", {})
        resources = backup.get("resources", {})
        total_items = sum(_count(resources.get(key)) for key in RESOURCES)
        fetched = sum(1 for key in RESOURCES if resources.get(key) is not None)
        failed = len(errors)
        failed_badge = badge(str(failed), "d") if failed else '<span class="zero">0</span>'
        tenant_id = f"tenant-{tenant_idx}"

        tenant_nav.append(f'<a href="#{tenant_id}">{_esc(label)}</a>')
        overview_rows.append(
            "<tr>"
            f"<td><strong>{_esc(label)}</strong></td>"
            f"<td class=\"meta\">{_esc(cloud)}</td>"
            f"<td>{fetched}/{len(RESOURCES)}</td>"
            f"<td>{total_items}</td>"
            f"<td>{failed_badge}</td>"
            f"<td class=\"meta\">{_esc(timestamp)}</td>"
            "</tr>"
        )

        resource_rows = []
        for key in RESOURCES:
            data = resources.get(key)
            error = errors.get(key)
            count = _count(data)
            page_name = f"tenant-{tenant_idx}-{_slug(key)}.html"
            _write_resource_report_page(asset_dir / page_name, tenant_idx, key, backup, generated)
            status = badge("error", "d") if error else badge("ok", "ok") if data is not None else '<span class="zero">no data</span>'
            resource_rows.append(
                "<tr>"
                f"<td><strong>{_esc(key)}</strong></td>"
                f"<td>{count}</td>"
                f"<td>{status}</td>"
                f"<td class=\"meta\">{_esc(RESOURCES[key].get('endpoint', ''))}</td>"
                f"<td><a href=\"{_esc(out_path.stem + '_files/' + page_name)}\">Open details</a></td>"
                "</tr>"
            )

        tenant_sections.append(f"""
<h2 id="{tenant_id}">{_esc(label)}</h2>
<div class="card">
  <div class="grid">
    <div class="stat"><span class="meta">Fetched endpoints</span><strong>{fetched}/{len(RESOURCES)}</strong></div>
    <div class="stat"><span class="meta">Objects/settings</span><strong>{total_items}</strong></div>
    <div class="stat"><span class="meta">Backup errors</span><strong>{failed}</strong></div>
  </div>
  <p class="meta">Cloud: <code>{_esc(cloud)}</code> &nbsp;|&nbsp; Backup: {_esc(timestamp)}</p>
  <table>
    <tr><th>Resource</th><th>Items</th><th>Status</th><th>Endpoint</th><th>Details</th></tr>
    {''.join(resource_rows)}
  </table>
</div>
""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<title>ZIA Full API Report</title>
<style>{CSS}</style>
</head>
<body>
<h1>ZIA Full API Report</h1>
<p class="meta">Generated: {generated}</p>

<div class="card">
  <p class="meta">This inventory report keeps the index page small and writes full resource details into linked pages beside this file. Fields that look like passwords, tokens, API keys, private keys, or pre-shared keys are redacted in the HTML output.</p>
  <p class="nav">{''.join(tenant_nav)}</p>
  <table>
    <tr><th>Tenant</th><th>Cloud</th><th>Fetched</th><th>Objects/settings</th><th>Errors</th><th>Backup time</th></tr>
    {''.join(overview_rows)}
  </table>
</div>

{''.join(tenant_sections)}
</body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _write_resource_report_page(out_path: Path, tenant_idx: int, resource_key: str,
                                backup: dict, generated: str):
    """Write one full resource detail page for the full inventory report."""
    meta = RESOURCES.get(resource_key, {})
    tenant_meta = backup.get("meta", {})
    label = tenant_meta.get("label") or f"Tenant {tenant_idx}"
    data = backup.get("resources", {}).get(resource_key)
    error = backup.get("errors", {}).get(resource_key)
    count = _count(data)

    if error:
        body = f'<div class="errbox">{_esc(error)}</div>'
    elif data is None:
        body = '<p class="meta">No data was returned for this endpoint.</p>'
    elif isinstance(data, list):
        preview_items = data[:100]
        body = [
            f'<p class="meta">Showing a preview of {len(preview_items)} of {len(data)} item(s). The full redacted JSON is below.</p>',
            _render_list(resource_key, preview_items),
            "<details><summary>Full redacted JSON</summary>",
            _safe_json(data),
            "</details>",
        ]
        body = "\n".join(body)
    elif isinstance(data, dict):
        body = _render_object_table(data) + "\n<details><summary>Full redacted JSON</summary>" + _safe_json(data) + "</details>"
    else:
        body = _preview(data, limit=2000)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<title>{_esc(label)} — {_esc(resource_key)}</title>
<style>{CSS}</style>
</head>
<body>
<p class="meta"><a href="../full_report.html">← Back to full report index</a></p>
<h1>{_esc(resource_key)}</h1>
<div class="card">
  <p><strong>{_esc(label)}</strong></p>
  <p class="meta">Generated: {generated}</p>
  <p class="meta">Endpoint: <code>{_esc(meta.get("method", "GET"))} {_esc(meta.get("endpoint", ""))}</code></p>
  <p class="meta">Items/settings: {count}</p>
  {f'<p class="warn">{_esc(meta.get("notes", ""))}</p>' if meta.get("notes") else ""}
</div>
{body}
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
