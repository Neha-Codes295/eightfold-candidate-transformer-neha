"""
Project: apply a runtime JSON config to select/rename/remap output fields.

Config schema:
{
  "fields": [
    {
      "name": "output_field_name",
      "from": "source.path[0].nested",   // optional dot+array path
      "normalize": "e164" | "lowercase" | "date",  // optional override
      "on_missing": "null" | "omit" | "error"       // optional per-field
    }
  ],
  "include_confidence": true | false,
  "include_provenance": true | false,
  "on_missing": "null" | "omit" | "error"  // global default
}
"""
import re
from typing import Any, Optional

from pipeline.normalize import _normalize_phone, normalize_date


# ---------------------------------------------------------------------------
# Path resolver — supports "skills[].name", "emails[0]", "links.github"
# ---------------------------------------------------------------------------

_ARRAY_INDEX_RE = re.compile(r"^(.+)\[(\d+)\]$")
_ARRAY_ITER_RE  = re.compile(r"^(.+)\[\]$")


def _resolve_path(obj: Any, path: str) -> Any:
    """
    Resolve a dot-notation + array-index path against obj.
    "emails[0]"     -> obj["emails"][0]
    "skills[].name" -> [s["name"] for s in obj["skills"]]
    "links.github"  -> obj["links"]["github"]
    """
    if not path:
        return obj

    parts = path.split(".")
    current = obj

    for part in parts:
        if current is None:
            return None

        # Check for array iteration: field[]
        m_iter = _ARRAY_ITER_RE.match(part)
        if m_iter:
            key = m_iter.group(1)
            arr = _get_key(current, key)
            if not isinstance(arr, list):
                return None
            # Remaining path will be resolved in next iteration — but since
            # we split on "." already, we need to handle this at end of parts.
            # Collect remaining parts (there may be none if this is the last part)
            current = arr
            continue

        # Check for array index: field[N]
        m_idx = _ARRAY_INDEX_RE.match(part)
        if m_idx:
            key = m_idx.group(1)
            idx = int(m_idx.group(2))
            arr = _get_key(current, key)
            if not isinstance(arr, list) or idx >= len(arr):
                return None
            current = arr[idx]
            continue

        current = _get_key(current, part)

    return current


def _resolve_path_full(obj: Any, path: str) -> Any:
    """
    Handles "skills[].name" as a full-path expression:
    split on the array-iteration segment and map the remainder over each element.
    """
    if "[]" not in path:
        return _resolve_path(obj, path)

    # Split at first []
    before, _, after = path.partition("[]")
    before = before.rstrip(".")
    after = after.lstrip(".")

    arr = _resolve_path(obj, before) if before else obj
    if not isinstance(arr, list):
        return None

    if not after:
        return arr

    return [_resolve_path(item, after) for item in arr]


def _get_key(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    if isinstance(obj, list):
        # If someone uses a key on a list, map it
        return [_get_key(item, key) for item in obj]
    return None


# ---------------------------------------------------------------------------
# Normalize overrides
# ---------------------------------------------------------------------------

def _apply_normalize(value: Any, normalize: str) -> Any:
    if normalize == "e164":
        if isinstance(value, list):
            return [_normalize_phone(str(v)) for v in value]
        return _normalize_phone(str(value)) if value is not None else None
    if normalize == "lowercase":
        if isinstance(value, list):
            return [str(v).lower() for v in value]
        return str(value).lower() if value is not None else None
    if normalize == "date":
        if isinstance(value, list):
            return [normalize_date(str(v)) for v in value]
        return normalize_date(str(value)) if value is not None else None
    return value


# ---------------------------------------------------------------------------
# Main projection function
# ---------------------------------------------------------------------------

class MissingFieldError(ValueError):
    pass


def apply_projection(merged: dict, config: Optional[dict]) -> dict:
    """
    Apply config projection to a merged candidate dict.
    If config is None, return merged as-is (strip internal _source_records key).
    """
    # Always strip internal key
    result = {k: v for k, v in merged.items() if not k.startswith("_")}

    if not config:
        return result

    fields_config = config.get("fields", [])
    include_confidence = config.get("include_confidence", True)
    include_provenance = config.get("include_provenance", True)
    global_on_missing = config.get("on_missing", "null")

    if not fields_config:
        # No field list — just toggle confidence/provenance
        if not include_confidence:
            result.pop("overall_confidence", None)
            for s in result.get("skills", []):
                s.pop("confidence", None)
        if not include_provenance:
            result.pop("provenance", None)
        return result

    projected = {}

    for field_spec in fields_config:
        out_name = field_spec.get("path") or field_spec.get("name")
        if not out_name:
            continue

        source_path = field_spec.get("from", out_name)
        normalize_override = field_spec.get("normalize")
        on_missing = field_spec.get("on_missing", global_on_missing)

        value = _resolve_path_full(result, source_path)

        if value is None:
            if on_missing == "error":
                raise MissingFieldError(
                    f"Field '{out_name}' (from '{source_path}') is missing or null "
                    f"and on_missing='error'"
                )
            elif on_missing == "omit":
                continue
            else:
                projected[out_name] = None
                continue

        if normalize_override:
            value = _apply_normalize(value, normalize_override)

        projected[out_name] = value

    if include_confidence:
        projected["overall_confidence"] = result.get("overall_confidence", 0.0)
    if include_provenance:
        projected["provenance"] = result.get("provenance", [])

    return projected
