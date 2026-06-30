"""
Validate: check the final output dict against the expected schema.
Logs warnings for type mismatches but never raises (graceful degradation).
"""
import sys
from typing import Any

SCHEMA = {
    "candidate_id": str,
    "full_name": (str, type(None)),
    "emails": list,
    "phones": list,
    "location": dict,
    "links": dict,
    "headline": (str, type(None)),
    "years_experience": (int, float, type(None)),
    "skills": list,
    "experience": list,
    "education": list,
    "provenance": list,
    "overall_confidence": (int, float),
}

LOCATION_SCHEMA = {
    "city": (str, type(None)),
    "region": (str, type(None)),
    "country": (str, type(None)),
}

LINKS_SCHEMA = {
    "linkedin": (str, type(None)),
    "github": (str, type(None)),
    "portfolio": (str, type(None)),
    "other": list,
}

SKILL_SCHEMA = {
    "name": str,
    "confidence": (int, float),
    "sources": list,
}


def _check_type(value: Any, expected: type | tuple, path: str, warnings: list) -> bool:
    if not isinstance(value, expected):
        warnings.append(
            f"Validation warning: '{path}' expected {expected}, got {type(value).__name__}"
        )
        return False
    return True


def validate_output(output: dict, warnings: list, is_projected: bool = False) -> dict:
    """
    Validate output dict against schema.
    When is_projected=True (config was applied), skip canonical schema enforcement
    since the config intentionally produces a different shape — only do light checks.
    When is_projected=False, fill in missing required keys with null/empty defaults.
    Returns (potentially repaired) output dict.
    """
    if is_projected:
        # Light validation only: warn on obvious type mismatches for fields that exist
        for key, value in output.items():
            if key in SCHEMA:
                _check_type(value, SCHEMA[key], key, warnings)
        return output

    # Full canonical schema validation
    for key, expected in SCHEMA.items():
        if key not in output:
            warnings.append(f"Validation: missing key '{key}' in output; defaulting")
            if expected == list or (isinstance(expected, tuple) and list in expected):
                output[key] = []
            elif expected == dict or (isinstance(expected, tuple) and dict in expected):
                output[key] = {}
            elif expected == str or (isinstance(expected, tuple) and str in expected):
                output[key] = None
            elif expected in ((int, float, type(None)), (int, float)):
                output[key] = None
            else:
                output[key] = None
        else:
            _check_type(output[key], expected, key, warnings)

    # Validate nested location
    loc = output.get("location")
    if isinstance(loc, dict):
        for k, exp in LOCATION_SCHEMA.items():
            if k not in loc:
                loc[k] = None
            elif not isinstance(loc[k], exp):
                warnings.append(f"Validation: location.{k} type mismatch")
                loc[k] = None

    # Validate nested links
    lnk = output.get("links")
    if isinstance(lnk, dict):
        for k, exp in LINKS_SCHEMA.items():
            if k not in lnk:
                lnk[k] = [] if exp == list else None
            elif not isinstance(lnk[k], exp):
                warnings.append(f"Validation: links.{k} type mismatch")
                lnk[k] = [] if exp == list else None

    # Validate skills list items
    for i, skill in enumerate(output.get("skills", [])):
        if not isinstance(skill, dict):
            warnings.append(f"Validation: skills[{i}] is not an object")
            continue
        for k, exp in SKILL_SCHEMA.items():
            if k not in skill:
                warnings.append(f"Validation: skills[{i}].{k} missing")

    return output
