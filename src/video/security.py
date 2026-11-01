"""Bounded HTTPS and local imports. Source content never becomes executable code."""
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit


class AccessError(RuntimeError):
    def __init__(self, message, *, status=0, retry_after=0):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


class Deferred(AccessError):
    """Capacity/usage wait, not a failed source or processing attempt."""
    def __init__(self, message, *, retry_after=300):
        super().__init__(message, retry_after=retry_after)


def validate_url(url, hosts):
    part = urlsplit(url)
    if (part.scheme != "https" or part.username or part.password or part.port not in (None, 443)
            or not part.hostname or part.hostname.lower() not in hosts or part.fragment
            or any(ord(c) < 33 for c in url)):
        raise AccessError("URL is not an allowed HTTPS source")
    return part


def public_addresses(host):
    addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise AccessError("private or non-global download address refused")
    return addresses


class _PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        address = public_addresses(self.host)[0]
        raw = socket.create_connection((address, 443), self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)


def request(url, *, hosts, method="GET", body=None, headers=None, max_bytes=2_000_000,
            timeout=20, sink=None, mime=None):
    """Pin DNS through TLS connection; revalidate redirects and never forward credentials."""
    deadline = time.monotonic() + timeout
    for redirect in range(4):
        part = validate_url(url, hosts)
        conn = _PinnedHTTPS(part.hostname, timeout=max(0.1, deadline - time.monotonic()))
        try:
            path = part.path or "/"
            if part.query:
                path += "?" + part.query
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                target = urljoin(url, response.getheader("Location", ""))
                dest = validate_url(target, hosts)
                if method != "GET" or (headers and dest.hostname != part.hostname):
                    raise AccessError("authenticated or write redirect refused")
                url = target
                continue
            if not 200 <= response.status < 300:
                retry = response.getheader("Retry-After", "0")
                reset = response.getheader("x-rate-limit-reset", "0")
                delay = max(float(retry) if retry.isdigit() else 0,
                            float(reset) - time.time() if reset.isdigit() else 0)
                raise AccessError(f"provider HTTP {response.status}", status=response.status, retry_after=max(0, delay))
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].lower()
            if mime and content_type not in mime:
                raise AccessError("unexpected response MIME type")
            length = response.getheader("Content-Length")
            if length and (not length.isdigit() or int(length) > max_bytes):
                raise AccessError("response exceeds byte budget")
            count, chunks = 0, []
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("download deadline")
                if conn.sock:
                    conn.sock.settimeout(max(0.1, deadline - time.monotonic()))
                chunk = response.read(65536)
                if not chunk:
                    break
                count += len(chunk)
                if count > max_bytes:
                    raise AccessError("response exceeds byte budget")
                if sink:
                    sink.write(chunk)
                    # Bound background bandwidth to ~2 MiB/s, leaving reply headroom.
                    time.sleep(len(chunk) / 2_097_152)
                else:
                    chunks.append(chunk)
            if method != "HEAD" and length is not None and count != int(length):
                raise AccessError("incomplete response body", status=response.status)
            return b"".join(chunks), dict(response.headers), count
        finally:
            conn.close()
    raise AccessError("redirect limit exceeded")


def json_request(url, *, hosts, payload=None, **kwargs):
    headers = {"Accept": "application/json", **kwargs.pop("headers", {})}
    body = None
    if payload is not None:
        body = json.dumps(payload, allow_nan=False).encode()
        headers["Content-Type"] = "application/json"
    data, _, _ = request(url, hosts=hosts, body=body, headers=headers, **kwargs)
    return json.loads(data)


def imported_file(path, roots):
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file() or not any(resolved.is_relative_to(Path(root).resolve()) for root in roots):
        raise AccessError("local media must be within an operator-approved import root")
    return resolved


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
