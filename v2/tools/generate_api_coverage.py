#!/usr/bin/env python3
"""Generate an endpoint-by-endpoint API coverage matrix.

The implemented coverage is read from resources.py. If a local checkout of the
official zscaler-sdk-python repository is available, the generator also scans
zscaler/zia modules and compares their endpoint surface to this tool.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK_ZIA_PATH = Path("/private/tmp/zscaler-sdk-python/zscaler/zia")
IGNORED_SDK_MODULES = {"__init__.py", "legacy.py", "zia_service.py"}
ZIA_BASE = "/zia/api/v1"
SANDBOX_BASE = "/zscsb"

sys.path.insert(0, str(REPO_ROOT))
from resources import RESOURCES  # noqa: E402


@dataclass(frozen=True)
class ImplementedEndpoint:
    key: str
    endpoint: str
    base_path: str
    methods: str
    coverage: str
    kind: str
    notes: str


@dataclass
class SdkEndpoint:
    module: str
    function: str
    method: str
    endpoint: str
    modules: set[str] = field(default_factory=set)
    functions: set[str] = field(default_factory=set)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sdk-zia-path",
        type=Path,
        default=DEFAULT_SDK_ZIA_PATH,
        help="Path to zscaler-sdk-python/zscaler/zia for optional comparison.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "API_COVERAGE_MATRIX.md",
        help="Markdown output path.",
    )
    return parser.parse_args()


def clean_endpoint(endpoint: str) -> str:
    endpoint = re.sub(r"\s+", "", endpoint or "")
    endpoint = endpoint.strip("'\"")
    endpoint = endpoint.replace("//", "/")
    if endpoint.startswith(ZIA_BASE):
        endpoint = endpoint[len(ZIA_BASE):]
    if endpoint.startswith("/"):
        endpoint = endpoint[1:]
    endpoint = endpoint.replace("{self._zia_base_endpoint}", "")
    endpoint = endpoint.replace("{self._sandbox_base_endpoint}", SANDBOX_BASE)
    endpoint = re.sub(r"\{[^{}]+\}", lambda m: "{" + m.group(0).strip("{}").split(".")[-1] + "}", endpoint)
    return endpoint


def base_path(endpoint: str) -> str:
    return clean_endpoint(endpoint).split("?", 1)[0].strip("/")


def endpoint_signature(endpoint: str) -> str:
    """Return a comparison key that ignores placeholder variable names."""
    return re.sub(r"\{[^{}]+\}", "{}", base_path(endpoint))


def markdown_escape(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("|", "\\|")
    return text


def truncate(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def format_resource_keys(rows: list[ImplementedEndpoint], limit: int = 8) -> str:
    keys = sorted({row.key for row in rows})
    if len(keys) <= limit:
        return ", ".join(keys)
    return ", ".join(keys[:limit]) + f", ... +{len(keys) - limit}"


def resource_methods(meta: dict) -> str:
    method = meta.get("method", "GET").upper()
    kind = meta.get("kind", "list")
    if kind == "list" and meta.get("writable"):
        return "GET, POST, PUT, DELETE"
    if kind == "settings":
        return "GET, PUT" if meta.get("writable", True) else "GET"
    return method


def resource_coverage(meta: dict) -> str:
    kind = meta.get("kind", "list")
    if kind == "list" and meta.get("writable"):
        return "Sync + report"
    if kind == "settings":
        return "Settings sync + report"
    if kind == "children":
        return "Report-only child fetch"
    if meta.get("method", "GET").upper() == "POST" and meta.get("raw"):
        return "Report-only raw export"
    return "Report-only"


def implemented_endpoints() -> list[ImplementedEndpoint]:
    records = []
    for key, meta in RESOURCES.items():
        endpoint = clean_endpoint(meta["endpoint"])
        records.append(
            ImplementedEndpoint(
                key=key,
                endpoint=endpoint,
                base_path=base_path(endpoint),
                methods=resource_methods(meta),
                coverage=resource_coverage(meta),
                kind=meta.get("kind", "list"),
                notes=truncate(meta.get("notes", "")),
            )
        )
    return sorted(records, key=lambda r: (r.endpoint.lower(), r.key))


def tool_operation_endpoints() -> list[ImplementedEndpoint]:
    """Endpoints used by the tool that are not resource inventory definitions."""
    return [
        ImplementedEndpoint(
            key="status_activate",
            endpoint="status/activate",
            base_path="status/activate",
            methods="POST",
            coverage="Runtime operation",
            kind="operation",
            notes="Used after sync when auto-activate is enabled.",
        )
    ]


def source_name(expr: ast.AST, source: str) -> str:
    segment = ast.get_source_segment(source, expr) or "value"
    segment = segment.strip()
    if segment in ("self._zia_base_endpoint", "cls._zia_base_endpoint"):
        return ZIA_BASE
    if segment in ("self._sandbox_base_endpoint", "cls._sandbox_base_endpoint"):
        return SANDBOX_BASE
    return "{" + segment.split(".")[-1] + "}"


def string_value(node: ast.AST, source: str, variables: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return variables.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                parts.append(source_name(part.value, source))
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = string_value(node.left, source, variables)
        right = string_value(node.right, source, variables)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "format_url" and node.args:
            return string_value(node.args[0], source, variables)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "upper":
            return string_value(node.func.value, source, variables)
    return None


def method_value(node: ast.AST, source: str, variables: dict[str, str]) -> str | None:
    value = string_value(node, source, variables)
    return value.upper() if value else None


def infer_method(function_name: str) -> str:
    lowered = function_name.lower()
    if lowered.startswith(("list_", "get_")):
        return "GET"
    if lowered.startswith(("add_", "create_", "scan_", "export_", "validate_")):
        return "POST"
    if lowered.startswith(("update_", "modify_")):
        return "PUT"
    if lowered.startswith(("delete_", "remove_")):
        return "DELETE"
    return "GET"


def endpoint_from_create_request(
    call: ast.Call,
    source: str,
    variables: dict[str, str],
    default_method: str,
) -> tuple[str, str] | None:
    method = default_method
    endpoint = None
    if call.args:
        parsed_method = method_value(call.args[0], source, variables)
        if parsed_method:
            method = parsed_method
    if len(call.args) > 1:
        endpoint = string_value(call.args[1], source, variables)
    for keyword in call.keywords:
        if keyword.arg == "method":
            parsed_method = method_value(keyword.value, source, variables)
            if parsed_method:
                method = parsed_method
        elif keyword.arg == "endpoint":
            endpoint = string_value(keyword.value, source, variables)
    if endpoint:
        return method, clean_endpoint(endpoint)
    return None


def scan_function(module: str, function: ast.FunctionDef, source: str) -> list[SdkEndpoint]:
    variables: dict[str, str] = {}
    method = infer_method(function.name)
    assigned_urls: list[str] = []
    create_request_urls: list[tuple[str, str]] = []

    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            value = string_value(node.value, source, variables)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id == "http_method":
                        parsed_method = method_value(node.value, source, variables)
                        if parsed_method:
                            method = parsed_method
                    elif value is not None:
                        variables[target.id] = value
                        if target.id in {"api_url", "endpoint", "url"}:
                            assigned_urls.append(clean_endpoint(value))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "create_request":
                parsed = endpoint_from_create_request(node, source, variables, method)
                if parsed:
                    create_request_urls.append(parsed)

    rows: list[SdkEndpoint] = []
    for parsed_method, endpoint in create_request_urls:
        if endpoint:
            rows.append(SdkEndpoint(module, function.name, parsed_method, endpoint))

    if not rows:
        for endpoint in assigned_urls:
            if endpoint:
                rows.append(SdkEndpoint(module, function.name, method, endpoint))
    return rows


def scan_sdk_zia_endpoints(sdk_zia_path: Path) -> list[SdkEndpoint]:
    if not sdk_zia_path.exists():
        return []

    found: dict[tuple[str, str], SdkEndpoint] = {}
    for path in sorted(sdk_zia_path.glob("*.py")):
        if path.name in IGNORED_SDK_MODULES:
            continue
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for endpoint in scan_function(path.stem, node, source):
                    if not endpoint.endpoint:
                        continue
                    key = (endpoint.method, endpoint.endpoint)
                    current = found.get(key)
                    if current is None:
                        endpoint.modules.add(endpoint.module)
                        endpoint.functions.add(endpoint.function)
                        found[key] = endpoint
                    else:
                        current.modules.add(endpoint.module)
                        current.functions.add(endpoint.function)

    return sorted(found.values(), key=lambda e: (e.endpoint.lower(), e.method))


def match_sdk_endpoint(
    sdk: SdkEndpoint,
    implemented_by_base: dict[str, list[ImplementedEndpoint]],
    implemented_by_signature: dict[str, list[ImplementedEndpoint]],
) -> tuple[str, str, str]:
    path = base_path(sdk.endpoint)
    signature = endpoint_signature(sdk.endpoint)
    method = sdk.method.upper()
    exact_matches = implemented_by_signature.get(signature, [])
    if exact_matches:
        keys = format_resource_keys(exact_matches)
        coverages = ", ".join(sorted({r.coverage for r in exact_matches}))
        return coverages, keys, "Exact implemented endpoint."

    parts = path.split("/")
    if len(parts) >= 2 and parts[-1].startswith("{") and parts[-1].endswith("}"):
        collection = "/".join(parts[:-1])
        matches = implemented_by_signature.get(endpoint_signature(collection), [])
        writable = [r for r in matches if "POST" in r.methods or "PUT" in r.methods or "DELETE" in r.methods]
        if method == "GET" and matches:
            keys = format_resource_keys(matches)
            return "Covered by collection inventory", keys, "Object detail endpoint is not fetched separately."
        if method in {"POST", "PUT", "DELETE"} and writable:
            keys = format_resource_keys(writable)
            return "Covered by generic sync write", keys, "Write operation is generated from the resource definition."

    for prefix_len in range(len(parts) - 1, 0, -1):
        candidate = "/".join(parts[:prefix_len])
        matches = implemented_by_signature.get(endpoint_signature(candidate), [])
        if matches:
            keys = format_resource_keys(matches)
            if any(r.coverage.startswith("Report-only") for r in matches):
                return "Partial", keys, "Base endpoint is report-only; this sub-endpoint is not fetched separately."
            return "Partial", keys, "Base resource is covered, but this specific helper/action endpoint is not."

    reverse_matches = [
        implemented
        for rows in implemented_by_base.values()
        for implemented in rows
        if implemented.base_path.startswith(f"{path}/")
    ]
    if reverse_matches:
        keys = format_resource_keys(reverse_matches)
        return "Partial", keys, "A narrower child/lite/all endpoint is covered, but the SDK base endpoint is not."

    if any(part.startswith("{") and part.endswith("}") for part in parts):
        prefix = []
        for part in parts:
            if part.startswith("{") and part.endswith("}"):
                break
            prefix.append(part)
        concrete_matches = [
            implemented
            for rows in implemented_by_base.values()
            for implemented in rows
            if implemented.base_path.startswith("/".join(prefix) + "/")
        ]
        if concrete_matches:
            keys = format_resource_keys(concrete_matches)
            return "Partial", keys, "Parameterized SDK endpoint is covered only for configured concrete endpoint variants."

    return "Not covered", "", ""


def implemented_table(rows: list[ImplementedEndpoint]) -> list[str]:
    lines = [
        "| Resource | Methods | Endpoint | Coverage | Kind | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{markdown_escape(row.key)}`",
                    markdown_escape(row.methods),
                    f"`/{markdown_escape(row.endpoint)}`",
                    markdown_escape(row.coverage),
                    markdown_escape(row.kind),
                    markdown_escape(row.notes),
                ]
            )
            + " |"
        )
    return lines


def sdk_table(
    sdk_rows: list[SdkEndpoint],
    implemented_rows: list[ImplementedEndpoint],
) -> tuple[list[str], dict[str, int]]:
    implemented_by_base: dict[str, list[ImplementedEndpoint]] = defaultdict(list)
    implemented_by_signature: dict[str, list[ImplementedEndpoint]] = defaultdict(list)
    for row in implemented_rows:
        implemented_by_base[row.base_path].append(row)
        implemented_by_signature[endpoint_signature(row.endpoint)].append(row)

    counts: dict[str, int] = defaultdict(int)
    lines = [
        "| SDK Module | Method | Endpoint | Coverage | Resource | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for row in sdk_rows:
        coverage, resources, notes = match_sdk_endpoint(row, implemented_by_base, implemented_by_signature)
        counts[coverage] += 1
        modules = ", ".join(sorted(row.modules or {row.module}))
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_escape(modules),
                    markdown_escape(row.method),
                    f"`/{markdown_escape(row.endpoint)}`",
                    markdown_escape(coverage),
                    markdown_escape(resources),
                    markdown_escape(notes),
                ]
            )
            + " |"
        )
    return lines, counts


def write_matrix(output: Path, sdk_zia_path: Path) -> None:
    resource_rows = implemented_endpoints()
    operation_rows = tool_operation_endpoints()
    implemented = resource_rows + operation_rows
    sdk_rows = scan_sdk_zia_endpoints(sdk_zia_path)
    sdk_lines, sdk_counts = sdk_table(sdk_rows, implemented) if sdk_rows else ([], {})
    resource_counts = defaultdict(int)
    for row in resource_rows:
        resource_counts[row.coverage] += 1

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# ZIA API Coverage Matrix",
        "",
        f"Generated: `{now}`",
        "",
        "This file is generated by `tools/generate_api_coverage.py`.",
        "Implemented coverage is derived from `resources.py`.",
        "The SDK comparison is derived from a local checkout of the official `zscaler-sdk-python` ZIA modules when available.",
        "",
        "## Summary",
        "",
        f"- Implemented resource definitions: `{len(resource_rows)}`",
        f"- Additional tool API operations: `{len(operation_rows)}`",
        f"- Official SDK endpoints discovered: `{len(sdk_rows)}`" if sdk_rows else "- Official SDK endpoints discovered: `0` (SDK path not found)",
        f"- SDK scan path: `{sdk_zia_path}`",
        "",
        "Implemented coverage breakdown:",
    ]
    for key in sorted(resource_counts):
        lines.append(f"- {key}: `{resource_counts[key]}`")
    if sdk_rows:
        lines.extend(["", "SDK endpoint comparison breakdown:"])
        for key in sorted(sdk_counts):
            lines.append(f"- {key}: `{sdk_counts[key]}`")

    lines.extend(
        [
            "",
            "## Legend",
            "",
            "- `Sync + report`: the tool backs up the collection and can create, update, and delete objects during sync.",
            "- `Settings sync + report`: the tool backs up a singleton settings object and can update it during sync.",
            "- `Report-only`: the tool fetches the endpoint for inventory/reporting but does not write it.",
            "- `Report-only child fetch`: the tool fetches detail endpoints once per parent object.",
            "- `Report-only raw export`: the tool fetches a non-JSON or export endpoint and stores decoded metadata/content where possible.",
            "- `Covered by collection inventory`: the SDK has a per-object GET, but this tool already inventories the object through the collection endpoint.",
            "- `Covered by generic sync write`: write calls are generated from `resources.py` rather than implemented as named SDK methods.",
            "- `Partial`: a related base resource is covered, but this exact helper/action endpoint is not fetched separately.",
            "- `Not covered`: no matching `resources.py` entry currently exists.",
            "",
            "## Implemented Resources",
            "",
        ]
    )
    lines.extend(implemented_table(resource_rows))

    lines.extend(["", "## Additional Tool API Operations", ""])
    lines.extend(implemented_table(operation_rows))

    lines.extend(["", "## Official SDK Endpoint Comparison", ""])
    if sdk_rows:
        lines.extend(sdk_lines)
    else:
        lines.append("SDK comparison was skipped because the SDK path was not found.")

    lines.append("")
    output.write_text("\n".join(lines))


def main() -> int:
    args = parse_args()
    write_matrix(args.output, args.sdk_zia_path)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
