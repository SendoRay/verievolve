"""Canonical serialization and identity for search-IR candidates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


_NON_SEMANTIC_KEYS = frozenset({"metadata"})


def _semantic_tree(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _semantic_tree(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in _NON_SEMANTIC_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_semantic_tree(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"IR contains a non-JSON value: {type(value).__name__}")


def canonical_json(candidate: Mapping[str, Any]) -> str:
    """Serialize semantic fields deterministically; labels do not affect identity."""
    return json.dumps(
        _semantic_tree(candidate),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def candidate_hash(candidate: Mapping[str, Any]) -> str:
    """Return the stable SHA-256 identity used by evaluation and synthesis caches."""
    return hashlib.sha256(canonical_json(candidate).encode("utf-8")).hexdigest()
