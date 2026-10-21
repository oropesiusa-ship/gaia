"""Passive bounded text extraction. Scripts/forms are ignored; code is only labelled data."""
import base64
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

from ..provenance import digest
from .fetch import validate_source
from .network import FetchError, normalize_url
from .schema import artifact, reference

VERSION = "passive_text_v1"
IGNORED = {"script", "style", "form", "iframe", "object", "embed", "svg", "noscript", "template"}
BLOCKS = {"p", "li", "dt", "dd", "td", "th", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}


class PassiveHTML(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.ignored = []
        self.pieces, self.current, self.title, self.headings, self.references = [], [], [], [], []
        self.in_title = False
        self.heading = None
        self.code_depth = 0
        self.current_code = False
        self.canonical = None

    def flush(self):
        text = " ".join("".join(self.current).split())
        if text:
            self.pieces.append(("CODE_DATA" if self.current_code else "TEXT", text))
        self.current, self.current_code = [], False

    def link(self, href):
        try:
            return normalize_url(urljoin(self.url, href))
        except (FetchError, ValueError):
            return None

    def handle_starttag(self, tag, attrs):
        if tag in IGNORED:
            self.ignored.append(tag)
        if self.ignored:
            return
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag in BLOCKS:
            self.flush()
        if tag == "pre":
            self.code_depth += 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading = (tag, [])
        if tag == "a" and attrs.get("href"):
            url = self.link(attrs["href"])
            if url and url not in self.references and len(self.references) < 64:
                self.references.append(url)
        if tag == "link" and attrs.get("rel") == "canonical" and attrs.get("href"):
            self.canonical = self.link(attrs["href"])

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag == "title":
            self.in_title = False
        if self.heading and tag == self.heading[0]:
            self.headings.append({"level": tag, "text": " ".join("".join(self.heading[1]).split())[:300]})
            self.heading = None
        if tag in BLOCKS:
            self.flush()
        if tag == "pre":
            self.code_depth = max(0, self.code_depth - 1)

    def handle_data(self, data):
        if self.ignored:
            return
        if self.in_title:
            self.title.append(data)
        elif data.strip():
            self.current.append(data)
            self.current_code |= self.code_depth > 0
        if self.heading:
            self.heading[1].append(data)


def extract(source):
    validate_source(source)
    p = source["payload"]
    cfg = p["policy"]["settings"]
    text = base64.b64decode(p["body_base64"]).decode("utf-8", errors="replace")
    references, headings, title, canonical = [], [], None, None
    if p["mime"] == "text/html":
        parser = PassiveHTML(p["url"])
        parser.feed(text)
        parser.close()
        parser.flush()
        pieces = parser.pieces
        title = " ".join("".join(parser.title).split())[:300] or None
        references, headings, canonical = parser.references, parser.headings[:64], parser.canonical
    elif p["mime"] == "application/json":
        try:
            data = json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise ValueError("Unsupported JSON text") from exc
        pieces = []
        def walk(value, depth=0):
            if depth > 20:
                return
            if isinstance(value, str):
                pieces.append(("TEXT", " ".join(value.split())))
            elif isinstance(value, dict):
                for key in sorted(value)[:100]:
                    walk(value[key], depth + 1)
            elif isinstance(value, list):
                for child in value[:100]:
                    walk(child, depth + 1)
        walk(data)
    else:
        pieces = [("TEXT", " ".join(line.split())) for line in text.splitlines() if line.strip()]
    fragments, count, truncated = [], 0, False
    for kind, paragraph in pieces:
        for offset in range(0, len(paragraph), 2000):
            chunk = paragraph[offset:offset + 2000]
            if count + len(chunk) > cfg["max_text_chars"] or len(fragments) >= cfg["max_fragments"]:
                truncated = True
                break
            fid = "fr" + digest({"source": source["artifact_id"], "index": len(fragments), "kind": kind, "text": chunk})[:24]
            fragments.append({"fragment_id": fid, "locator": "passive-text:" + str(len(fragments)), "kind": kind, "text": chunk,
                              "start": count, "end": count + len(chunk), "source_ref": reference(source)})
            count += len(chunk) + 1
        if truncated:
            break
    patterns = {"IGNORE_PRIOR_INSTRUCTIONS": r"ignore\s+(?:all\s+)?(?:previous|GAIA|prior)\s+(?:instructions|policy)",
                "EXECUTION_DIRECTIVE": r"(?:execute|run)\s+(?:this\s+)?(?:command|script)|curl\s+[^\n]+\|\s*(?:bash|sh)",
                "AUTHORITY_IMPERSONATION": r"system_instruction|authorized_action|network_authorized"}
    flags = sorted(k for k, pattern in patterns.items() if re.search(pattern, text, re.I))
    version_match = re.search(r"/(\d{1,2}\.\d{1,2})(?:/|\.)", urlsplit(p["url"]).path)
    version = version_match.group(1) if version_match else None
    title_version = re.search(r"Python\s+(\d{1,2}\.\d{1,2}\.\d{1,2})\s+documentation", title or "", re.I)
    if title_version:
        version = title_version.group(1)
    commit = re.search(r"/(?:blob|raw|commit)/([a-f0-9]{40})(?:/|$)", urlsplit(p["url"]).path)
    release = re.search(r"/releases/tag/(v?\d{1,3}(?:\.\d{1,3}){1,3})(?:/|$)", urlsplit(p["url"]).path)
    modified = None
    try:
        modified = parsedate_to_datetime(p["http_metadata"].get("last-modified", "")).isoformat()
    except (ValueError, TypeError, AttributeError):
        pass
    return artifact("EXTRACTION", {"source_ref": reference(source), "content_hash": p["content_hash"], "extractor_version": VERSION,
                    "title": title, "headings": headings, "fragments": fragments, "references": references, "canonical_url": canonical,
                    "version": version, "version_basis": "SOURCE_TITLE" if title_version else "URL_PATH" if version else "UNKNOWN", "publication_date": None,
                    "source_commit": commit.group(1) if commit else None, "source_release": release.group(1) if release else None,
                    "update_date": modified, "date_basis": "HTTP_LAST_MODIFIED_SOURCE_ASSERTED" if modified else "UNKNOWN",
                    "suspicious_patterns": flags, "active_content_executed": False, "truncated": truncated}, created_at=source["created_at"],
                    limitations=["Passive normalized-text locators cite retained original content hash; they are not original HTML byte offsets.",
                                 "Dates/versions are source metadata, not proof of universal validity; active content and forms were not executed."])
