"""Bounded public fetch with revalidated redirects, robots, passive bytes and fixed headers."""
import base64
from datetime import datetime
import hashlib
import http.client
import re
import socket
import ssl
import time
import threading
from urllib.parse import urljoin, urlsplit
import urllib.robotparser
import zlib

from ..provenance import digest
from .network import FetchError, PinnedConnection, normalize_url, resolve_public
from .policy import MIMES, classify, identity, settings
from .request import validate_request
from .schema import artifact, reference, timestamp, validate

USER_AGENT = "GAIA/0.7 (directed evidence research; read-only)"


class Fetcher:
    def __init__(self, request, configuration=None):
        validate_request(request)
        self.request = request
        self.cfg = settings(configuration)
        self.started = time.monotonic()
        self.last_request = None
        self.requests = 0
        self.wire_bytes = 0
        self.decoded_bytes = 0
        self.robots = {}
        self.events = []

    def _remaining(self):
        return min(self.cfg["max_duration_seconds"], self.request["payload"]["budget"]["max_duration_seconds"]) - (time.monotonic() - self.started)

    def _url(self, url):
        p = self.request["payload"]
        return normalize_url(url, allow_http=p["allow_http"] and not self.cfg["https_only"], domains=p["allowed_domains"])

    def _authorized(self):
        if not self.cfg["network_enabled"] or not self.request["payload"]["network_authorized"]:
            raise FetchError("NETWORK_NOT_AUTHORIZED")
        if self._remaining() <= 0:
            raise FetchError("DURATION_BUDGET_EXHAUSTED")

    def _reserve(self):
        self._authorized()
        maximum = min(self.cfg["max_requests"], self.request["payload"]["budget"]["max_requests"])
        if self.requests >= maximum:
            raise FetchError("REQUEST_BUDGET_EXHAUSTED")
        if self.last_request is not None:
            pause = self.cfg["min_interval_seconds"] - (time.monotonic() - self.last_request)
            if pause > 0:
                time.sleep(min(pause, max(0, self._remaining())))
        self._authorized()
        self.requests += 1
        self.last_request = time.monotonic()

    def _read_body(self, response, connection, *, limit=None, method="GET"):
        encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
        if encoding not in ("identity", "gzip"):
            raise FetchError("UNSUPPORTED_CONTENT_ENCODING")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
        maximum = min(limit or self.cfg["max_response_bytes"], self.cfg["max_response_bytes"])
        declared = response.getheader("Content-Length")
        if declared and (not declared.isdigit() or int(declared) > maximum):
            raise FetchError("RESPONSE_TOO_LARGE")
        wire, chunks, size = bytearray(), [], 0
        if method == "HEAD":
            return b"", b"", encoding
        while True:
            if self._remaining() <= 0:
                raise FetchError("DURATION_BUDGET_EXHAUSTED")
            transport = getattr(connection, "transport_socket", None) or connection.sock
            if transport is not None:
                transport.settimeout(min(self.cfg["timeout_seconds"], self._remaining()))
            chunk = response.read1(min(16384, maximum - len(wire) + 1))
            if not chunk:
                break
            wire.extend(chunk)
            self.wire_bytes += len(chunk)
            if len(wire) > maximum:
                raise FetchError("RESPONSE_TOO_LARGE")
            allowed_total = min(self.cfg["max_total_bytes"], self.request["payload"]["budget"]["max_total_bytes"])
            if self.wire_bytes > allowed_total:
                raise FetchError("TOTAL_BYTE_BUDGET_EXHAUSTED")
            try:
                decoded = decoder.decompress(chunk, self.cfg["max_decompressed_bytes"] - size + 1) if decoder else chunk
            except zlib.error as exc:
                raise FetchError("INVALID_COMPRESSED_CONTENT") from exc
            size += len(decoded)
            self.decoded_bytes += len(decoded)
            if size > self.cfg["max_decompressed_bytes"]:
                raise FetchError("DECOMPRESSED_TOO_LARGE")
            if self.decoded_bytes > allowed_total:
                raise FetchError("TOTAL_DECODED_BUDGET_EXHAUSTED")
            chunks.append(decoded)
        if decoder and (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
            raise FetchError("TRUNCATED_OR_MULTIPART_GZIP_DENIED")
        return bytes(wire), b"".join(chunks), encoding

    def _exchange(self, url, *, method="GET", robots_document=False):
        self._authorized()
        if method not in ("GET", "HEAD"):
            raise FetchError("HTTP_METHOD_DENIED")
        url = self._url(url)
        parts = urlsplit(url)
        port = 443 if parts.scheme == "https" else 80
        addresses = resolve_public(parts.hostname, port, min(self.cfg["timeout_seconds"], self._remaining()))
        last_error = None
        for address in addresses[:4]:
            self._reserve()
            connection = PinnedConnection(parts.hostname, address, port, tls=parts.scheme == "https", timeout=min(self.cfg["timeout_seconds"], self._remaining()))
            response = None
            # A wall deadline also interrupts slow headers/chunk trailers inside
            # http.client, where per-read socket timeouts alone are insufficient.
            watchdog = threading.Timer(max(.001, self._remaining()), connection.abort)
            watchdog.daemon = True
            watchdog.start()
            try:
                connection.request(method, parts.path or "/", headers={"User-Agent": USER_AGENT, "Accept": "text/html, text/plain, application/json",
                                                                        "Accept-Encoding": "identity", "Connection": "close"})
                response = connection.getresponse()
                if not connection.verified:
                    raise FetchError("DESTINATION_NOT_PINNED")
                attestation = {"resolved_public": True, "peer_public": True, "peer_matches_pinned": True,
                               "dns_answer_hash": digest(addresses), "resolved_count": len(addresses),
                               "tls_hostname_verified": parts.scheme == "https"}
                headers = {}
                for key in ("Content-Type", "ETag", "Last-Modified", "Date", "Location"):
                    value = response.getheader(key)
                    if value and len(value) <= 2048 and not any(ord(c) < 32 or ord(c) == 127 for c in value):
                        headers[key.lower()] = value
                if response.status in (301, 302, 303, 307, 308):
                    return {"url": url, "status": response.status, "headers": headers, "attestation": attestation, "body": b"", "wire": b"", "encoding": "identity"}
                if robots_document and response.status in (404, 410):
                    return {"url": url, "status": response.status, "headers": {}, "attestation": attestation, "body": b"", "wire": b"", "encoding": "identity"}
                if response.status != 200:
                    raise FetchError("HTTP_STATUS_UNAVAILABLE")
                mime = (headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                if mime not in MIMES:
                    raise FetchError("MIME_NOT_SUPPORTED")
                wire, body, encoding = self._read_body(response, connection, limit=65536 if robots_document else None, method=method)
                return {"url": url, "status": response.status, "headers": {k: v for k, v in headers.items() if k != "location"},
                        "attestation": attestation, "body": body, "wire": wire, "encoding": encoding}
            except (OSError, ssl.SSLError, TimeoutError, http.client.HTTPException):
                if connection.deadline_expired or self._remaining() <= 0:
                    raise FetchError("DURATION_BUDGET_EXHAUSTED")
                last_error = "TRANSPORT_UNAVAILABLE"
            finally:
                try:
                    if response is not None:
                        response.close()
                finally:
                    try:
                        connection.close(force=True)
                    finally:
                        watchdog.cancel()
                        watchdog.join(timeout=.1)
        raise FetchError(last_error or "NO_USABLE_PUBLIC_ADDRESS")

    def _redirected(self, url, *, robots_document=False, method="GET"):
        chain = []
        current = self._url(url)
        maximum = min(self.cfg["max_redirects"], self.request["payload"]["budget"]["max_redirects"])
        while True:
            if not robots_document:
                parts = urlsplit(current)
                if classify(parts.hostname, parts.path)[0] not in self.request["payload"]["allowed_source_classes"]:
                    raise FetchError("SOURCE_CLASS_NOT_AUTHORIZED")
                self._robots(current)
            result = self._exchange(current, method=method, robots_document=robots_document)
            chain.append({"url": result["url"], "status": result["status"], "network": result["attestation"]})
            if result["status"] not in (301, 302, 303, 307, 308):
                return result, chain
            if len(chain) > maximum:
                raise FetchError("REDIRECT_LIMIT")
            location = result["headers"].get("location")
            if not location:
                raise FetchError("INVALID_REDIRECT")
            current = self._url(urljoin(current, location))  # Revalidates before DNS/connection.

    def _robots(self, url):
        parts = urlsplit(url)
        origin = parts.scheme + "://" + parts.netloc
        if origin not in self.robots:
            result, chain = self._redirected(origin + "/robots.txt", robots_document=True)
            parser = urllib.robotparser.RobotFileParser()
            if result["status"] in (404, 410):
                parser.parse([])
            else:
                parser.parse(result["body"].decode("utf-8", errors="replace").splitlines())
            delay = parser.crawl_delay("GAIA")
            if delay and delay > self.request["payload"]["budget"]["max_duration_seconds"]:
                raise FetchError("ROBOTS_DELAY_EXCEEDS_BUDGET")
            self.robots[origin] = (parser, {"content_hash": hashlib.sha256(result["body"]).hexdigest(), "status": result["status"],
                                           "rules_base64": base64.b64encode(result["body"]).decode("ascii"),
                                           "checked_url": origin + "/robots.txt", "retrieval_chain": chain, "crawl_delay": delay})
        parser, proof = self.robots[origin]
        if not parser.can_fetch("GAIA", url):
            raise FetchError("ROBOTS_DENIED")
        if proof["crawl_delay"] and self.last_request is not None:
            pause = proof["crawl_delay"] - (time.monotonic() - self.last_request)
            if pause > self._remaining():
                raise FetchError("ROBOTS_DELAY_EXCEEDS_BUDGET")
            if pause > 0:
                time.sleep(pause)
        return proof

    def fetch(self, url, *, method="GET"):
        if method not in ("GET", "HEAD"):
            raise FetchError("HTTP_METHOD_DENIED")
        self._authorized()
        url = self._url(url)
        if url not in self.request["payload"]["urls"]:
            raise FetchError("URL_OUTSIDE_REQUEST")
        result, chain = self._redirected(url, method=method)
        final = urlsplit(result["url"])
        source_class, publisher = classify(final.hostname, final.path)
        if source_class not in self.request["payload"]["allowed_source_classes"]:
            raise FetchError("SOURCE_CLASS_NOT_AUTHORIZED")
        robots = [p for _, p in self.robots.values()]
        return artifact("SOURCE", {"request_ref": reference(self.request), "requested_url": url, "url": result["url"], "domain": final.hostname,
            "source_class": source_class, "publisher_group": publisher, "origin": "LIVE_PUBLIC_FETCH",
            "mime": result["headers"]["content-type"].split(";", 1)[0].strip().lower(), "http_metadata": result["headers"],
            "content_hash": hashlib.sha256(result["body"]).hexdigest(), "wire_hash": hashlib.sha256(result["wire"]).hexdigest(),
            "content_identity": digest({"url": result["url"], "body_hash": hashlib.sha256(result["body"]).hexdigest()}),
            "body_base64": base64.b64encode(result["body"]).decode("ascii"), "decoded_bytes": len(result["body"]), "wire_bytes": len(result["wire"]),
            "content_encoding": result["encoding"], "retrieval_chain": chain, "robots": robots,
            "policy": identity(self.cfg), "method": method}, limitations=["Public source capture; TLS and destination checks are retrieval attestations, not a signature over external truth.",
                                                                       "Original passive bytes retained for replay; no cookies, credentials or arbitrary response headers persisted."])


def validate_source(value):
    validate(value)
    if value["kind"] != "SOURCE":
        raise ValueError("Source artifact required")
    p = value["payload"]
    expected = {"request_ref", "requested_url", "url", "domain", "source_class", "publisher_group", "origin", "mime", "http_metadata",
                "content_hash", "wire_hash", "content_identity", "body_base64", "decoded_bytes", "wire_bytes", "content_encoding", "retrieval_chain", "robots", "policy", "method"}
    if set(p) != expected:
        raise ValueError("Invalid source fields")
    cfg = settings({"external_research": p["policy"]["settings"]})
    if p["policy"] != identity(cfg) or p["origin"] not in ("LIVE_PUBLIC_FETCH", "LOCAL_REPLAY_FIXTURE"):
        raise ValueError("Invalid source origin/policy")
    if p["mime"] not in MIMES or p["method"] not in ("GET", "HEAD"):
        raise ValueError("Invalid passive source format")
    if (not isinstance(p["body_base64"], str) or len(p["body_base64"]) > 4 * ((cfg["max_decompressed_bytes"] + 2) // 3)
            or any(type(p[k]) is not int or p[k] < 0 for k in ("wire_bytes", "decoded_bytes"))
            or not isinstance(p["wire_hash"], str) or not re.fullmatch(r"[a-f0-9]{64}", p["wire_hash"])):
        raise ValueError("Invalid source size/hash encoding")
    body = base64.b64decode(p["body_base64"], validate=True)
    if len(body) != p["decoded_bytes"] or len(body) > cfg["max_decompressed_bytes"] or p["wire_bytes"] > cfg["max_response_bytes"] or p["content_hash"] != hashlib.sha256(body).hexdigest():
        raise ValueError("Source content identity/size mismatch")
    if p["content_identity"] != digest({"url": p["url"], "body_hash": p["content_hash"]}):
        raise ValueError("Source content address mismatch")
    for key in ("url", "requested_url"):
        if normalize_url(p[key], allow_http=not cfg["https_only"]) != p[key]:
            raise ValueError("Noncanonical source URL")
    parts = urlsplit(p["url"])
    if p["domain"] != parts.hostname or (p["source_class"], p["publisher_group"]) != classify(parts.hostname, parts.path):
        raise ValueError("Source class/identity mismatch")
    if set(p["http_metadata"]) - {"content-type", "etag", "last-modified", "date"}:
        raise ValueError("Unexpected persisted HTTP metadata")
    if p["origin"] == "LIVE_PUBLIC_FETCH":
        if (not cfg["network_enabled"] or not p["robots"] or not p["retrieval_chain"] or len(p["retrieval_chain"]) > cfg["max_redirects"] + 1
                or p["retrieval_chain"][0]["url"] != p["requested_url"] or p["retrieval_chain"][-1]["url"] != p["url"] or p["retrieval_chain"][-1]["status"] != 200):
            raise ValueError("Missing bounded retrieval provenance")
        rules = {}
        for proof in p["robots"]:
            # Original captures before this optional field existed cannot supply
            # an offline robots proof; published captures include bounded rules.
            if "rules_base64" not in proof:
                raise ValueError("Robots rules required for replayable politeness proof")
            raw_rules = base64.b64decode(proof["rules_base64"], validate=True)
            if len(raw_rules) > 65536 or hashlib.sha256(raw_rules).hexdigest() != proof["content_hash"] or proof["status"] not in (200, 404, 410):
                raise ValueError("Invalid robots provenance")
            robot = urllib.robotparser.RobotFileParser()
            robot.parse(raw_rules.decode("utf-8", errors="replace").splitlines() if proof["status"] == 200 else [])
            origin = urlsplit(proof["checked_url"])
            rules[origin.scheme + "://" + origin.netloc] = robot
        for step in p["retrieval_chain"] + [s for r in p["robots"] for s in r["retrieval_chain"]]:
            normalize_url(step["url"], allow_http=not cfg["https_only"])
            if any(step["network"][k] is not True for k in ("resolved_public", "peer_public", "peer_matches_pinned")):
                raise ValueError("Missing public destination attestation")
            if urlsplit(step["url"]).scheme == "https" and step["network"]["tls_hostname_verified"] is not True:
                raise ValueError("TLS hostname not verified")
        for step in p["retrieval_chain"]:
            parts = urlsplit(step["url"])
            parser = rules.get(parts.scheme + "://" + parts.netloc)
            if parser is None or not parser.can_fetch("GAIA", step["url"]):
                raise ValueError("Robots does not authorize captured source")
    return value
