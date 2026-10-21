"""URL/DNS restrictions and pinned public-IP connections. Never uses proxy/env credentials."""
import http.client
import ipaddress
import queue
import re
import socket
import ssl
import threading
from urllib.parse import quote, unquote, urlsplit, urlunsplit


class FetchError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def public_ip(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise FetchError("INVALID_RESOLVED_ADDRESS") from exc
    if (not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_loopback or ip.is_link_local
            or isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None
                or ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network("64:ff9b:1::/48"))):
        raise FetchError("NONPUBLIC_DESTINATION")
    return str(ip)


def normalize_url(url, *, allow_http=False, domains=()):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in url) or "\\" in url:
        raise FetchError("INVALID_URL")
    try:
        parts = urlsplit(url)
        if parts.scheme not in (("https", "http") if allow_http else ("https",)):
            raise FetchError("SCHEME_DENIED")
        if parts.username is not None or parts.password is not None or parts.query:
            raise FetchError("CREDENTIALS_OR_QUERY_DENIED")
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        port = parts.port
        if not host or "%" in host or port not in (None, 443 if parts.scheme == "https" else 80):
            raise FetchError("HOST_OR_PORT_DENIED")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if ("." not in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".localdomain", ".home", ".lan"))
                    or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p) for p in host.split("."))):
                raise FetchError("INTERNAL_OR_INVALID_HOST")
        else:
            host = public_ip(host)
        if domains and host not in domains:
            raise FetchError("DOMAIN_NOT_AUTHORIZED")
        decoded = unquote(parts.path or "/")
        if any(ord(c) < 32 or ord(c) == 127 for c in decoded) or "\\" in decoded:
            raise FetchError("INVALID_PATH")
        path = quote(decoded, safe="/:-._~!$&'()*+,;=@")
        return urlunsplit((parts.scheme, f"[{host}]" if ":" in host else host, path, "", ""))
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, FetchError):
            raise
        raise FetchError("INVALID_URL") from exc


def resolve_public(host, port, timeout):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        result = queue.Queue(maxsize=1)
        def lookup():
            try:
                result.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except OSError:
                result.put(None)
        worker = threading.Thread(target=lookup, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise FetchError("DNS_TIMEOUT")
        answers = result.get_nowait()
        if not answers:
            raise FetchError("DNS_UNAVAILABLE")
        ips = sorted({public_ip(a[4][0]) for a in answers}, key=lambda a: (ipaddress.ip_address(a).version, a))
        if not ips:
            raise FetchError("DNS_UNAVAILABLE")
        return ips
    return [public_ip(host)]


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, address, port, *, tls, timeout):
        super().__init__(host, port=port, timeout=timeout)
        self.address = public_ip(address)
        self.tls = tls
        self.verified = False
        self.deadline_expired = False

    def abort(self):
        self.deadline_expired = True
        sock = getattr(self, "transport_socket", None) or self.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self, *, force=False):
        # HTTPConnection.getresponse closes its socket eagerly on Connection: close.
        # Keep sole ownership until the bounded body reader finishes, so its TLS
        # socket deadline remains adjustable. Fetcher always force-closes in finally.
        if force:
            super().close()

    def connect(self):
        family = socket.AF_INET6 if ":" in self.address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        self.transport_socket = sock
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.address, self.port, 0, 0) if family == socket.AF_INET6 else (self.address, self.port))
            if public_ip(sock.getpeername()[0]) != self.address:
                raise FetchError("PEER_PIN_MISMATCH")
            if self.tls:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            if public_ip(sock.getpeername()[0]) != self.address:
                raise FetchError("PEER_PIN_MISMATCH")
            self.sock = sock
            self.transport_socket = sock
            self.verified = True
        except BaseException:
            sock.close()
            raise
