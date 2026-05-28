"""
ZIA API Client — OneAPI OAuth or legacy session auth with pagination support.
"""

import json
import time
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request


AUTH_MODE_LEGACY = "legacy"
AUTH_MODE_ONEAPI = "oneapi"
USER_AGENT = "ZIA-Backup-Restore/1.0"


def obfuscate_api_key(api_key: str, timestamp: int) -> str:
    """Produce the obfuscated API key required by ZIA's authentication endpoint.

    ZIA does not accept the raw API key. Instead it expects a 12-character derived
    key built from the last 6 digits of the current millisecond timestamp:

      high = last 6 digits of timestamp  (e.g. "123456")
      low  = high >> 1, zero-padded to 6  (e.g. "061728")

    The resulting key is formed by indexing into api_key:
      - for each digit d in high: append api_key[d]
      - for each digit d in low:  append api_key[d + 2]

    The same timestamp must be sent in the JSON payload so the server can
    validate the derived key.
    """
    api_key = _clean_api_key(api_key)
    if len(api_key) < 12:
        raise ValueError("Legacy API key must be at least 12 characters long.")
    high = str(timestamp)[-6:]
    low = str(int(high) >> 1).zfill(6)
    key = ""
    for c in high:
        key += api_key[int(c)]
    for c in low:
        key += api_key[int(c) + 2]
    return key


def legacy_obfuscation_debug(api_key: str, timestamp: int) -> dict:
    """Return non-secret details for comparing legacy API key obfuscation."""
    clean_key = _clean_api_key(api_key)
    high = str(timestamp)[-6:]
    low = str(int(high) >> 1).zfill(6)
    obfuscated = obfuscate_api_key(clean_key, timestamp)
    return {
        "timestamp": timestamp,
        "high": high,
        "low": low,
        "api_key_length": len(clean_key),
        "obfuscated_length": len(obfuscated),
    }


def _clean_api_key(api_key: str) -> str:
    """Trim whitespace and accidental surrounding quotes from a legacy API key."""
    value = (api_key or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value


def _clean_vanity_domain(vanity_domain: str) -> str:
    """Accept a bare vanity domain or a pasted zslogin URL and return the name."""
    value = (vanity_domain or "").strip().lower()
    value = value.removeprefix("https://").removeprefix("http://").strip("/")
    for suffix in (
        ".zslogin.net",
        ".zsloginbeta.net",
        ".zsloginalpha.net",
        ".zsloginzscalerbeta.net",
    ):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value.split(".zslogin", 1)[0] if ".zslogin" in value else value


def _normalise_oneapi_cloud(cloud: str) -> str:
    """Normalise optional OneAPI cloud input to the SDK-style cloud name."""
    value = (cloud or "").strip().lower()
    value = value.removeprefix("https://").removeprefix("http://").strip("/")
    if value in ("", "default", "prod", "production", "api.zsapi.net"):
        return "production"
    if value.startswith("api.") and value.endswith(".zsapi.net"):
        return value[len("api.") : -len(".zsapi.net")]
    if value.startswith("zsapi.") and value.endswith(".net"):
        return value[len("zsapi.") : -len(".net")]
    return value


def _normalise_legacy_cloud(cloud: str) -> str:
    """Accept a legacy cloud hostname or pasted URL and return only the host."""
    value = (cloud or "").strip().lower()
    value = value.removeprefix("https://").removeprefix("http://").strip("/")
    if "/" in value:
        value = value.split("/", 1)[0]
    aliases = {
        "zscaler": "zsapi.zscaler.net",
        "zscloud": "zsapi.zscloud.net",
        "zscalerone": "zsapi.zscalerone.net",
        "zscalertwo": "zsapi.zscalertwo.net",
        "zscalerthree": "zsapi.zscalerthree.net",
        "zscalerbeta": "zsapi.zscalerbeta.net",
        "zscalergov": "zsapi.zscalergov.net",
    }
    return aliases.get(value, value)


def normalise_legacy_cloud(cloud: str) -> str:
    """Public wrapper used by config/UI code to store canonical legacy hosts."""
    return _normalise_legacy_cloud(cloud)


def _oneapi_api_base(cloud: str) -> str:
    """Return the OneAPI ZIA v1 base URL for the selected cloud."""
    root = "https://api.zsapi.net"
    if cloud and cloud != "production":
        root = f"https://api.{cloud}.zsapi.net"
    return f"{root}/zia/api/v1"


def _oneapi_token_url(vanity_domain: str, cloud: str) -> str:
    """Return the Zidentity OAuth token endpoint for the selected cloud."""
    if cloud == "production":
        return f"https://{vanity_domain}.zslogin.net/oauth2/v1/token"
    return f"https://{vanity_domain}.zslogin{cloud}.net/oauth2/v1/token"


def _config_value(tenant_cfg: dict, *names: str) -> str:
    """Read snake_case or SDK-style camelCase config values."""
    for name in names:
        value = tenant_cfg.get(name)
        if value:
            return value
    return ""


class ZIAClient:
    def __init__(
        self,
        cloud: str = "",
        username: str = "",
        password: str = "",
        api_key: str = "",
        *,
        auth_mode: str = AUTH_MODE_LEGACY,
        client_id: str = "",
        client_secret: str = "",
        vanity_domain: str = "",
        oneapi_cloud: str = "",
        partner_id: str = "",
    ):
        """Initialise the client for a single ZIA tenant.

        Does NOT authenticate immediately — call authenticate() before making
        any API requests, or use the client as a context manager.

        Args:
            cloud:         Legacy tenant API hostname, e.g. 'zsapi.zscloud.net'.
            username:      Legacy admin email address, e.g. 'admin@company.com'.
            password:      Legacy admin password.
            api_key:       Legacy API key from ZIA Admin Portal.
            auth_mode:     'oneapi' for Zidentity OAuth, otherwise 'legacy'.
            client_id:     OneAPI client ID.
            client_secret: OneAPI client secret.
            vanity_domain: OneAPI vanity domain, without '.zslogin.net'.
            oneapi_cloud:  Optional OneAPI cloud name, e.g. 'beta'.
            partner_id:    Optional OneAPI partner ID header value.
        """
        self.auth_mode = (auth_mode or AUTH_MODE_LEGACY).strip().lower()
        if self.auth_mode in ("oauth", "oauth2", "zidentity"):
            self.auth_mode = AUTH_MODE_ONEAPI
        if self.auth_mode not in (AUTH_MODE_ONEAPI, AUTH_MODE_LEGACY):
            raise ValueError("auth_mode must be 'oneapi' or 'legacy'")

        self.cloud = _normalise_legacy_cloud(cloud)
        self.username = username
        self.password = password
        self.api_key = _clean_api_key(api_key)
        self.client_id = client_id
        self.client_secret = client_secret
        self.vanity_domain = _clean_vanity_domain(vanity_domain)
        self.oneapi_cloud = _normalise_oneapi_cloud(oneapi_cloud)
        self.partner_id = partner_id
        self._access_token = None
        self._token_expires_at = 0.0

        if self.auth_mode == AUTH_MODE_ONEAPI:
            self.base = _oneapi_api_base(self.oneapi_cloud)
        else:
            self.base = f"https://{self.cloud}/api/v1"

        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self._authenticated = False

    @classmethod
    def from_config(cls, tenant_cfg: dict) -> "ZIAClient":
        """Build a client from a tenant block in config.json."""
        auth_mode = (tenant_cfg.get("auth_mode") or AUTH_MODE_LEGACY).strip().lower()
        if auth_mode in ("oauth", "oauth2", "zidentity", AUTH_MODE_ONEAPI):
            return cls(
                auth_mode=AUTH_MODE_ONEAPI,
                client_id=_config_value(tenant_cfg, "client_id", "clientId"),
                client_secret=_config_value(tenant_cfg, "client_secret", "clientSecret"),
                vanity_domain=_config_value(tenant_cfg, "vanity_domain", "vanityDomain"),
                oneapi_cloud=_config_value(tenant_cfg, "oneapi_cloud", "cloud"),
                partner_id=_config_value(tenant_cfg, "partner_id", "partnerId"),
            )
        return cls(
            _config_value(tenant_cfg, "cloud", "zia_cloud", "ziaCloud"),
            _config_value(tenant_cfg, "username", "userName"),
            _config_value(tenant_cfg, "password"),
            _config_value(tenant_cfg, "api_key", "apiKey"),
            auth_mode=AUTH_MODE_LEGACY,
        )

    def authenticate(self):
        """Authenticate with OneAPI OAuth or the legacy ZIA session endpoint."""
        if self.auth_mode == AUTH_MODE_ONEAPI:
            return self._authenticate_oneapi()
        return self._authenticate_legacy()

    def _authenticate_legacy(self):
        """Authenticate against the ZIA API and store the session cookie.

        Calls POST /authenticatedSession with the obfuscated API key and
        current millisecond timestamp. On success, urllib stores the returned
        JSESSIONID cookie in self.jar, which is automatically sent with all
        subsequent requests.

        Raises:
            RuntimeError: If the server returns a non-200 response, with the
                          HTTP status code and response body in the message.
        """
        timestamp = int(time.time() * 1000)
        missing = [
            name for name, value in (
                ("cloud", self.cloud),
                ("username", self.username),
                ("password", self.password),
                ("api_key", self.api_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Legacy config is missing: {', '.join(missing)}")
        debug = legacy_obfuscation_debug(self.api_key, timestamp)
        print(
            "  Legacy key obfuscation: "
            f"timestamp={debug['timestamp']} high={debug['high']} low={debug['low']} "
            f"api_key_length={debug['api_key_length']} obfuscated_length={debug['obfuscated_length']}"
        )
        obf_key = obfuscate_api_key(self.api_key, timestamp)
        payload = json.dumps({
            "username": self.username,
            "password": self.password,
            "apiKey": obf_key,
            "timestamp": timestamp,
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/authenticatedSession", data=payload, method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Cache-Control", "no-cache")
        req.add_header("User-Agent", USER_AGENT)
        try:
            with self.opener.open(req) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            hint = ""
            if e.code == 406:
                hint = (
                    " Legacy ZIA returned 406. Check that the API key is the Cloud Service API key "
                    "for this exact cloud and that legacy API access is enabled for the tenant."
                )
            raise RuntimeError(f"Auth failed {e.code}:{hint} {body[:700]}")
        self._authenticated = True
        return resp

    def _authenticate_oneapi(self):
        """Authenticate against OneAPI/Zidentity with client credentials."""
        if self._access_token and time.time() < (self._token_expires_at - 60):
            self._authenticated = True
            return {"access_token": self._access_token, "expires_at": self._token_expires_at}

        missing = [
            name for name, value in (
                ("client_id", self.client_id),
                ("client_secret", self.client_secret),
                ("vanity_domain", self.vanity_domain),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"OneAPI config is missing: {', '.join(missing)}")

        payload = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "audience": "https://api.zscaler.com",
        }).encode()
        req = urllib.request.Request(
            _oneapi_token_url(self.vanity_domain, self.oneapi_cloud),
            data=payload,
            method="POST",
        )
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with self.opener.open(req) as r:
                raw = r.read()
                resp = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"OneAPI auth failed {e.code}: {e.read().decode()[:300]}")
        token = resp.get("access_token")
        if not token:
            raise RuntimeError("OneAPI auth failed: token response did not contain access_token")
        expires_in = int(resp.get("expires_in", 3600))
        self._access_token = token
        self._token_expires_at = time.time() + expires_in
        self._authenticated = True
        return resp

    def _add_auth_headers(self, req: urllib.request.Request):
        """Attach OneAPI authorization headers when OAuth is in use."""
        if self.auth_mode != AUTH_MODE_ONEAPI:
            return
        if not self._access_token or time.time() >= (self._token_expires_at - 60):
            self.authenticate()
        req.add_header("Authorization", f"Bearer {self._access_token}")
        if self.partner_id:
            req.add_header("x-partner-id", self.partner_id)

    def _request(self, method: str, path: str, body=None,
                 _retries: int = 3) -> dict | list | None:
        """Send an authenticated HTTP request and return the parsed JSON response.

        Automatically re-authenticates if not yet authenticated. Handles HTTP 429
        (rate limiting) with exponential backoff: waits 2s, 4s, then 8s before
        giving up after 3 retries.

        Args:
            method:   HTTP verb ('GET', 'POST', 'PUT', 'DELETE').
            path:     API path relative to /api/v1/, e.g. 'firewallFilteringRules'.
            body:     Optional dict to serialise as the JSON request body.
            _retries: Remaining retry attempts for 429 responses (internal use).

        Returns:
            Parsed JSON as dict or list, or None for empty responses (e.g. DELETE 204).

        Raises:
            RuntimeError: For any non-429 HTTP error, or when retries are exhausted.
        """
        if not self._authenticated:
            self.authenticate()
        url = f"{self.base}/{path.lstrip('/')}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        self._add_auth_headers(req)
        try:
            with self.opener.open(req) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode()
            if e.code == 401 and self.auth_mode == AUTH_MODE_ONEAPI and _retries > 0:
                self._authenticated = False
                self._access_token = None
                self.authenticate()
                return self._request(method, path, body, _retries - 1)
            if e.code == 429 and _retries > 0:
                # Rate limited — back off and retry
                wait = 2 ** (4 - _retries)  # 2s, 4s, 8s
                time.sleep(wait)
                return self._request(method, path, body, _retries - 1)
            raise RuntimeError(f"HTTP {e.code} on {method} {path}: {body_txt[:400]}")

    def _request_raw(self, method: str, path: str, body=None, headers: dict | None = None,
                     _retries: int = 3) -> dict:
        """Send an authenticated request and return status, headers, and raw bytes.

        This is used for endpoints such as policy export that return a ZIP or other
        non-JSON payload instead of normal API JSON.
        """
        if not self._authenticated:
            self.authenticate()
        url = f"{self.base}/{path.lstrip('/')}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        self._add_auth_headers(req)
        for name, value in (headers or {}).items():
            req.add_header(name, value)
        try:
            with self.opener.open(req) as r:
                return {
                    "status": getattr(r, "status", None),
                    "headers": dict(r.headers.items()),
                    "body": r.read(),
                }
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode(errors="replace")
            if e.code == 401 and self.auth_mode == AUTH_MODE_ONEAPI and _retries > 0:
                self._authenticated = False
                self._access_token = None
                self.authenticate()
                return self._request_raw(method, path, body, headers, _retries - 1)
            if e.code == 429 and _retries > 0:
                wait = 2 ** (4 - _retries)
                time.sleep(wait)
                return self._request_raw(method, path, body, headers, _retries - 1)
            raise RuntimeError(f"HTTP {e.code} on {method} {path}: {body_txt[:400]}")

    def get(self, path: str, params: dict = None) -> dict | list | None:
        """Send a GET request, optionally appending query parameters.

        Use this for single-object endpoints (settings, readonly objects).
        For list endpoints that require pagination, use get_paginated() instead.
        """
        if params:
            path = f"{path}?{urllib.parse.urlencode(params)}"
        return self._request("GET", path)

    def get_raw(self, path: str, headers: dict | None = None) -> dict:
        """Send a GET request and return raw response bytes plus metadata."""
        return self._request_raw("GET", path, headers=headers)

    def post(self, path: str, body: dict) -> dict | None:
        """Send a POST request to create a new resource.

        Returns the created object (including the server-assigned ID), or None.
        """
        return self._request("POST", path, body)

    def post_raw(self, path: str, body=None, headers: dict | None = None) -> dict:
        """Send a POST request and return raw response bytes plus metadata."""
        return self._request_raw("POST", path, body, headers=headers)

    def put(self, path: str, body: dict) -> dict | None:
        """Send a PUT request to update an existing resource or settings object.

        For list resources the path must include the object ID, e.g. 'firewallFilteringRules/123'.
        For settings objects the path is the base endpoint, e.g. 'advancedSettings'.
        """
        return self._request("PUT", path, body)

    def delete(self, path: str) -> None:
        """Send a DELETE request to remove a resource by its full path including ID."""
        self._request("DELETE", path)

    def get_paginated(self, path: str, page_size: int = 1000, max_pages: int = 100) -> list:
        """Fetch all pages from a paginated list endpoint and return the combined list.

        Sends GET requests with pageSize and page parameters, incrementing the page
        number until the server returns fewer items than the page size (indicating the
        last page). Handles two response shapes:
          - Plain list: the response body is a JSON array directly.
          - Wrapped dict: the items are under a 'list' or 'urlCategories' key.

        If the endpoint returns a non-list, non-dict response (e.g. a settings object),
        the loop exits and returns an empty list — callers should fall back to get().
        """
        results = []
        page = 1
        seen_pages = set()
        while page <= max_pages:
            sep = "&" if "?" in path else "?"
            data = self._request("GET", f"{path}{sep}pageSize={page_size}&page={page}")
            if not data:
                break
            if isinstance(data, list):
                if not data:
                    break
                page_signature = json.dumps(data[:3], sort_keys=True, default=str)
                if page_signature in seen_pages:
                    print(f"  Pagination stopped for {path}: repeated page data at page {page}.")
                    break
                seen_pages.add(page_signature)
                results.extend(data)
                if len(data) > page_size:
                    print(f"  Pagination stopped for {path}: endpoint returned {len(data)} items in one response.")
                    break
                if len(data) < page_size:
                    break
                page += 1
            elif isinstance(data, dict):
                # some endpoints wrap in a list key
                items = data.get("list", data.get("urlCategories", []))
                if not isinstance(items, list):
                    break
                page_signature = json.dumps(items[:3], sort_keys=True, default=str)
                if page_signature in seen_pages:
                    print(f"  Pagination stopped for {path}: repeated page data at page {page}.")
                    break
                seen_pages.add(page_signature)
                results.extend(items)
                if len(items) > page_size:
                    print(f"  Pagination stopped for {path}: endpoint returned {len(items)} items in one response.")
                    break
                if len(items) < page_size:
                    break
                page += 1
            else:
                break
        if page > max_pages:
            print(f"  Pagination stopped for {path}: reached {max_pages} pages.")
        return results

    def activate(self) -> dict:
        """Commit all pending configuration changes in ZIA.

        ZIA uses a two-phase commit model: write operations (POST/PUT/DELETE) stage
        changes but do not apply them until POST /status/activate is called.
        This should be called once after all changes have been applied.
        """
        return self._request("POST", "/status/activate")

    def logout(self):
        """End the legacy session or clear the cached OneAPI access token.

        Safe to call even if not authenticated or if the server returns an error —
        exceptions are silently swallowed. Always call this in a finally block to
        avoid leaving stale sessions open.
        """
        if self.auth_mode == AUTH_MODE_ONEAPI:
            self._access_token = None
            self._token_expires_at = 0.0
            self._authenticated = False
            return
        if not self._authenticated:
            return
        try:
            self._request("DELETE", "/authenticatedSession")
        except Exception:
            pass
        self._authenticated = False
