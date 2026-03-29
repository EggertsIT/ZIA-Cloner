"""
ZIA API Client — session-based auth with cookie, pagination support.
"""

import urllib.request
import urllib.parse
import json
import time
import http.cookiejar


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
    high = str(timestamp)[-6:]
    low = str(int(high) >> 1).zfill(6)
    key = ""
    for c in high:
        key += api_key[int(c)]
    for c in low:
        key += api_key[int(c) + 2]
    return key


class ZIAClient:
    def __init__(self, cloud: str, username: str, password: str, api_key: str):
        """Initialise the client for a single ZIA tenant.

        Does NOT authenticate immediately — call authenticate() before making
        any API requests, or use the client as a context manager.

        Args:
            cloud:    Tenant API hostname, e.g. 'zsapi.zscloud.net'.
            username: Admin email address, e.g. 'admin@company.com'.
            password: Admin password (plain text — stored in memory only).
            api_key:  API key from ZIA Admin Portal → API Key Management.
        """
        self.base = f"https://{cloud}/api/v1"
        self.username = username
        self.password = password
        self.api_key = api_key
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self._authenticated = False

    def authenticate(self):
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
        try:
            with self.opener.open(req) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Auth failed {e.code}: {e.read().decode()[:300]}")
        self._authenticated = True
        return resp

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
        req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode()
            if e.code == 429 and _retries > 0:
                # Rate limited — back off and retry
                wait = 2 ** (4 - _retries)  # 2s, 4s, 8s
                time.sleep(wait)
                return self._request(method, path, body, _retries - 1)
            raise RuntimeError(f"HTTP {e.code} on {method} {path}: {body_txt[:400]}")

    def get(self, path: str, params: dict = None) -> dict | list | None:
        """Send a GET request, optionally appending query parameters.

        Use this for single-object endpoints (settings, readonly objects).
        For list endpoints that require pagination, use get_paginated() instead.
        """
        if params:
            path = f"{path}?{urllib.parse.urlencode(params)}"
        return self._request("GET", path)

    def post(self, path: str, body: dict) -> dict | None:
        """Send a POST request to create a new resource.

        Returns the created object (including the server-assigned ID), or None.
        """
        return self._request("POST", path, body)

    def put(self, path: str, body: dict) -> dict | None:
        """Send a PUT request to update an existing resource or settings object.

        For list resources the path must include the object ID, e.g. 'firewallFilteringRules/123'.
        For settings objects the path is the base endpoint, e.g. 'advancedSettings'.
        """
        return self._request("PUT", path, body)

    def delete(self, path: str) -> None:
        """Send a DELETE request to remove a resource by its full path including ID."""
        self._request("DELETE", path)

    def get_paginated(self, path: str, page_size: int = 1000) -> list:
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
        while True:
            sep = "&" if "?" in path else "?"
            data = self._request("GET", f"{path}{sep}pageSize={page_size}&page={page}")
            if not data:
                break
            if isinstance(data, list):
                if not data:
                    break
                results.extend(data)
                if len(data) < page_size:
                    break
                page += 1
            elif isinstance(data, dict):
                # some endpoints wrap in a list key
                items = data.get("list", data.get("urlCategories", []))
                results.extend(items)
                if len(items) < page_size:
                    break
                page += 1
            else:
                break
        return results

    def activate(self) -> dict:
        """Commit all pending configuration changes in ZIA.

        ZIA uses a two-phase commit model: write operations (POST/PUT/DELETE) stage
        changes but do not apply them until POST /status/activate is called.
        This should be called once after all changes have been applied.
        """
        return self._request("POST", "/status/activate")

    def logout(self):
        """End the authenticated session by deleting the session cookie server-side.

        Safe to call even if not authenticated or if the server returns an error —
        exceptions are silently swallowed. Always call this in a finally block to
        avoid leaving stale sessions open.
        """
        try:
            self._request("DELETE", "/authenticatedSession")
        except Exception:
            pass
        self._authenticated = False
