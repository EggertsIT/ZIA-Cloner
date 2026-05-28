"""
API call and rate-limit time estimates.
"""
from resources import RESOURCES, MIGRATION_ORDER


READ_PER_SECOND = 2
READ_PER_HOUR = 1000
WRITE_PER_SECOND = 1
WRITE_PER_HOUR = 400


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def estimate_counts_time(counts: dict[str, int]) -> dict:
    """Estimate elapsed time from API call counts using conservative defaults."""
    get_count = counts.get("GET", 0)
    write_count = counts.get("POST", 0) + counts.get("PUT", 0) + counts.get("DELETE", 0)

    read_seconds = max(
        get_count / READ_PER_SECOND if get_count else 0,
        get_count / READ_PER_HOUR * 3600 if get_count else 0,
    )
    write_seconds = max(
        write_count / WRITE_PER_SECOND if write_count else 0,
        write_count / WRITE_PER_HOUR * 3600 if write_count else 0,
    )
    total_seconds = read_seconds + write_seconds
    return {
        "read_seconds": read_seconds,
        "write_seconds": write_seconds,
        "total_seconds": total_seconds,
        "read_time": _duration(read_seconds),
        "write_time": _duration(write_seconds),
        "total_time": _duration(total_seconds),
    }


def estimate_backup_counts(resource_count: int) -> dict[str, int]:
    """Estimate minimum backup reads. Pagination can make real count higher."""
    return {"GET": resource_count, "POST": 0, "PUT": 0, "DELETE": 0}


def estimate_apply_counts(diff: dict, *, no_delete: bool = False, sync_sensitive: bool = False,
                          include_activate: bool = False) -> dict[str, int]:
    """Estimate API calls needed to apply a diff to the target tenant."""
    counts = {"GET": 0, "POST": 0, "PUT": 0, "DELETE": 0}
    writable_diff = diff.get("writable", {})

    for key in MIGRATION_ORDER:
        if key not in writable_diff:
            continue
        meta = RESOURCES[key]
        if meta.get("sensitive") and not sync_sensitive:
            continue

        data = writable_diff[key]
        kind = meta.get("kind", "list")
        if kind == "settings":
            if data.get("changes"):
                counts["PUT"] += 1
            continue

        creates = len(data.get("to_create", []))
        updates = len(data.get("to_update", []))
        deletes = 0 if no_delete else len(data.get("to_delete", []))
        if creates or updates or deletes:
            counts["GET"] += 1  # _get_existing() before applying this resource
        counts["POST"] += creates
        counts["PUT"] += updates
        counts["DELETE"] += deletes

    if include_activate and (counts["POST"] or counts["PUT"] or counts["DELETE"]):
        counts["POST"] += 1

    return counts


def merge_counts(*items: dict[str, int]) -> dict[str, int]:
    merged = {"GET": 0, "POST": 0, "PUT": 0, "DELETE": 0}
    for item in items:
        for method in merged:
            merged[method] += item.get(method, 0)
    return merged


def format_estimate(label: str, counts: dict[str, int]) -> list[str]:
    timing = estimate_counts_time(counts)
    total = sum(counts.values())
    return [
        f"{label}: {total} estimated API call(s)",
        f"GET {counts.get('GET', 0)}, POST {counts.get('POST', 0)}, "
        f"PUT {counts.get('PUT', 0)}, DELETE {counts.get('DELETE', 0)}",
        f"Estimated minimum time: {timing['total_time']} "
        f"(reads {timing['read_time']}, writes {timing['write_time']})",
    ]
