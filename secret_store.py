"""
Protect and restore secret config values with native OS storage.
"""
import base64
import ctypes
import hashlib
import subprocess
import sys
from ctypes import wintypes


SECRET_FIELDS = {"client_secret", "clientSecret", "password", "api_key", "apiKey"}
PROTECTED_MARKER = "__zia_cloner_protected__"
KEYCHAIN_SERVICE = "ZIA Backup & Restore"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _crypt_protect_data(value: str) -> str:
    data = value.encode("utf-8")
    input_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    output_blob = DATA_BLOB()

    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "ZIA Backup & Restore secret",
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        protected = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.b64encode(protected).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def _crypt_unprotect_data(value: str) -> str:
    data = base64.b64decode(value.encode("ascii"))
    input_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    output_blob = DATA_BLOB()

    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        unprotected = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return unprotected.decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def _keychain_account(tenant_name: str, field: str) -> str:
    raw = f"zia-backup-restore:{tenant_name}:{field}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"zia-backup-restore-{digest}"


def _run_security(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/usr/bin/security", *args],
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def _keychain_store(account: str, value: str):
    _run_security(["delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account])
    result = _run_security(
        ["add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", account, "-w", value]
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Unable to save secret to macOS Keychain.").strip()
        raise RuntimeError(message)


def _keychain_load(account: str) -> str:
    result = _run_security(["find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"])
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Unable to read secret from macOS Keychain.").strip()
        raise RuntimeError(message)
    return result.stdout.rstrip("\n")


def is_protected_value(value) -> bool:
    return isinstance(value, dict) and value.get(PROTECTED_MARKER) is True


def protect_value(value, tenant_name: str, field: str):
    if not value or is_protected_value(value):
        return value
    if sys.platform == "darwin":
        account = _keychain_account(tenant_name, field)
        _keychain_store(account, str(value))
        return {
            PROTECTED_MARKER: True,
            "scope": "macos-keychain",
            "service": KEYCHAIN_SERVICE,
            "account": account,
        }
    if sys.platform != "win32":
        return value
    return {
        PROTECTED_MARKER: True,
        "scope": "windows-user",
        "value": _crypt_protect_data(str(value)),
    }


def unprotect_value(value):
    if not is_protected_value(value):
        return value
    scope = value.get("scope")
    if scope == "windows-user":
        if sys.platform != "win32":
            raise RuntimeError("This config contains Windows-protected secrets and must be opened on Windows.")
        return _crypt_unprotect_data(value["value"])
    if scope == "macos-keychain":
        if sys.platform != "darwin":
            raise RuntimeError("This config contains macOS Keychain secrets and must be opened on macOS.")
        return _keychain_load(value["account"])
    raise RuntimeError(f"Unknown protected secret scope: {scope}")


def protect_config(cfg: dict) -> dict:
    for tenant_name in ("tenant_a", "tenant_b"):
        tenant = cfg.get(tenant_name)
        if not isinstance(tenant, dict):
            continue
        for field in SECRET_FIELDS:
            if field in tenant:
                tenant[field] = protect_value(tenant[field], tenant_name, field)
    return cfg


def unprotect_config(cfg: dict) -> dict:
    for tenant_name in ("tenant_a", "tenant_b"):
        tenant = cfg.get(tenant_name)
        if not isinstance(tenant, dict):
            continue
        for field in SECRET_FIELDS:
            if field in tenant:
                tenant[field] = unprotect_value(tenant[field])
    return cfg
