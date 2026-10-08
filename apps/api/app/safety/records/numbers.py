"""Incident number normalization.

Numbers are written in several forms (``LCY-2026-037``, ``LCY 2026-040``,
``LCY-2026-30``, ``lcy-2026-37``). They are stored and compared in one form:
an upper-case prefix, the four-digit year and the sequence padded to three
digits, joined by hyphens (``LCY-2026-037``). Anything else is rejected
rather than guessed.
"""

import re

_NUMBER = re.compile(r"^\s*([A-Za-z]{2,10})[\s_-]*(\d{4})[\s_-]+(\d{1,6})\s*$")


class InvalidIncidentNumberError(ValueError):
    pass


def normalize_incident_number(raw: str | None) -> str | None:
    """The normalized number, or None for a blank one."""
    if raw is None or not raw.strip():
        return None
    match = _NUMBER.match(raw)
    if match is None:
        raise InvalidIncidentNumberError(
            f"{raw.strip()!r} is not an incident number; use the form LCY-2026-037"
        )
    prefix, year, sequence = match.groups()
    return f"{prefix.upper()}-{year}-{int(sequence):03d}"
