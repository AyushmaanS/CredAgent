"""Secret masking applied before every model call and every event/log write.

Two layers:
1. Exact values registered at runtime (captured credentials, our own API keys).
2. Pattern rules for strings that look like credentials, so an unregistered
   secret visible on a page is still masked before it can reach a model.

Masking is deliberately biased toward over-masking. The placeholder never
contains any part of the original value.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

PLACEHOLDER = "[REDACTED:{label}]"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    )),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("prefixed_key", re.compile(
        r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{8,}"
        r"|\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}"
        r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
        r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
        r"|\bxox[abposr]-[A-Za-z0-9-]{10,}"
        r"|\bAIza[0-9A-Za-z_-]{30,}"
        r"|\btvly-[A-Za-z0-9_-]{16,}"
        r"|\bAKIA[0-9A-Z]{16}\b"
        r"|\bya29\.[0-9A-Za-z_-]{20,}"
        r"|\bsecret_[A-Za-z0-9]{20,}"
        r"|\bntn_[A-Za-z0-9]{20,}"
    )),
    # Labelled assignments such as `client_secret: abc...` or `"api_key": "abc..."`.
    ("labelled_secret", re.compile(
        r"(?i)((?:client[_ -]?secret|api[_ -]?key|access[_ -]?token|secret[_ -]?key|password|token)"
        r"[\"']?\s*[:=]\s*[\"']?)([^\s\"',;]{8,})"
    )),
]

_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-+/=]{32,}")
_URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]]+")
_URL_SEGMENT_RE = re.compile(r"[^/?&=#.:]{32,}")


def _mask_match(m: re.Match[str]) -> str:
    return PLACEHOLDER.format(label="high_entropy") if looks_random(m.group(0)) else m.group(0)


_SLUG_RE = re.compile(r"[a-z0-9]{1,20}(?:[-_][a-z0-9]{1,20})+")


def _mask_url_segment(m: re.Match[str]) -> str:
    # Lowercase word-slugs ("8128613-api-keys-create-api-keys") are page paths, not secrets.
    return m.group(0) if _SLUG_RE.fullmatch(m.group(0)) else _mask_match(m)


def _mask_tokens(text: str) -> str:
    return _TOKEN_RE.sub(_mask_match, text)


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def looks_random(token: str) -> bool:
    """Long, mixed-class, high-entropy token (e.g. an unprefixed client secret)."""
    if len(token) < 32:
        return False
    if re.fullmatch(r"[0-9a-fA-F]{32,}", token):
        return True  # hex secrets (e.g. 40-char client secrets) have entropy < 4 bits/char
    if shannon_entropy(token) < 4.0:
        return False
    classes = sum(
        bool(re.search(p, token)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]")
    )
    return classes >= 2


class Masker:
    def __init__(self, known_values: Iterable[str] = ()) -> None:
        self._known: dict[str, str] = {}
        for v in known_values:
            self.register(v)

    def register(self, value: str, label: str = "secret") -> None:
        """Register an exact secret value. Short values are refused (too collision-prone
        to mask safely); callers must treat such a credential as not safely capturable."""
        if not value:
            return
        if len(value) < 6:
            raise ValueError("refusing to register a secret shorter than 6 characters")
        self._known[value] = label

    def mask_text(self, text: str) -> str:
        if not text:
            return text
        # Longest first so a value containing another value is fully replaced.
        for value in sorted(self._known, key=len, reverse=True):
            if value in text:
                text = text.replace(value, PLACEHOLDER.format(label=self._known[value]))
        for label, pattern in PATTERNS:
            if label == "labelled_secret":
                text = pattern.sub(
                    lambda m: m.group(1) + PLACEHOLDER.format(label="labelled_secret"), text
                )
            else:
                text = pattern.sub(PLACEHOLDER.format(label=label), text)
        # High-entropy pass. Inside URLs, judge each path/query segment separately so
        # ordinary paths survive (research needs real URLs) while secret-looking query
        # values or path segments are still masked. Outside URLs, keep '/' and '+' in
        # tokens so base64 secrets are judged whole.
        out, last = [], 0
        for m in _URL_RE.finditer(text):
            out.append(_mask_tokens(text[last:m.start()]))
            out.append(_URL_SEGMENT_RE.sub(_mask_url_segment, m.group(0)))
            last = m.end()
        out.append(_mask_tokens(text[last:]))
        return "".join(out)

    def mask(self, obj: Any) -> Any:
        """Recursively mask strings inside dicts/lists/tuples. Keys are masked too."""
        if isinstance(obj, str):
            return self.mask_text(obj)
        if isinstance(obj, dict):
            return {self.mask(k): self.mask(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.mask(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self.mask(v) for v in obj)
        return obj

    def contains_known(self, text: str) -> bool:
        return any(v in text for v in self._known)


def masked_display(value: str) -> str:
    """Safe display: length and a 4-char prefix only for values long enough that the
    prefix is not a meaningful fraction of the secret."""
    if len(value) >= 24:
        return f"{value[:4]}…({len(value)} chars)"
    return f"•••({len(value)} chars)"
