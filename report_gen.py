"""
report_gen.py — HTML report generator.
"""
import json
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
"""


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
    out_path.write_text(html)
    return out_path
