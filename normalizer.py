"""
Selection normalizer — converts raw bookmaker selection Usn codes
into canonical_outcome + line_value + line_value2.

Usn is consistent across ALL companies:
  1X2 markets      : '1', 'X', '2'
  Double Chance    : '1X', 'X2', '12'
  BTTS / DNB       : 'Y'/'N' or '1'/'2'
  Over/Under       : 'o 2,5' / 'u 2,5'
  Asian Handicap   : 'H -1,5' / 'A +1,5'
  Asian O/U        : 'o 2,25' / 'u 2,25'
"""
import re
from typing import Optional


def _parse_line(usn: str) -> tuple[Optional[float], Optional[float]]:
    """
    Extract up to two line values from a Usn string.
    e.g. 'H -1,5'      → (-1.5, None)
         'o 2,25'      → (2.25, None)
         'H -1,5 & -2' → (-1.5, -2.0)   ← Asian quarter ball
    Commas are used as decimal separators in Usn.
    """
    normalized = usn.replace(",", ".")
    nums = re.findall(r"[-+]?\d+\.?\d*", normalized)
    v1 = float(nums[0]) if len(nums) >= 1 else None
    v2 = float(nums[1]) if len(nums) >= 2 else None
    return v1, v2


def normalize(umid: Optional[int], osn: Optional[str], usn: Optional[str],
              home_team: Optional[str] = None, away_team: Optional[str] = None) -> dict:
    """
    Returns a dict with keys:
        canonical_outcome, line_value, line_value2, raw_outcome
    """
    raw_outcome = osn or usn or ""
    result = dict(canonical_outcome=None, line_value=None, line_value2=None, raw_outcome=raw_outcome)

    if not usn or umid is None:
        return result

    u = usn.strip()
    u_lower = u.lower()
    u_upper = u.upper()

    # ── 1X2 / DNB / Double Chance ────────────────────────────────────────────
    if u_upper in ("1", "H"):
        result["canonical_outcome"] = "home"
        return result
    if u_upper in ("2", "A"):
        result["canonical_outcome"] = "away"
        return result
    if u_upper in ("X", "D"):
        result["canonical_outcome"] = "draw"
        return result
    if u_upper == "Y":
        result["canonical_outcome"] = "yes"
        return result
    if u_upper == "N":
        result["canonical_outcome"] = "no"
        return result
    if u_upper in ("1X",):
        result["canonical_outcome"] = "1X"
        return result
    if u_upper in ("X2",):
        result["canonical_outcome"] = "X2"
        return result
    if u_upper in ("12",):
        result["canonical_outcome"] = "12"
        return result

    # ── Over/Under (goals, corners, cards, team totals) ──────────────────────
    if u_lower.startswith("o ") or u_lower.startswith("o,"):
        result["canonical_outcome"] = "over"
        v1, v2 = _parse_line(u)
        result["line_value"] = v1
        result["line_value2"] = v2
        return result
    if u_lower.startswith("u ") or u_lower.startswith("u,"):
        result["canonical_outcome"] = "under"
        v1, v2 = _parse_line(u)
        result["line_value"] = v1
        result["line_value2"] = v2
        return result

    # ── Asian Handicap (home/away spread) ────────────────────────────────────
    if u_upper.startswith("H ") or u_upper.startswith("H-") or u_upper.startswith("H+"):
        result["canonical_outcome"] = "home"
        v1, v2 = _parse_line(u)
        result["line_value"] = v1
        result["line_value2"] = v2
        return result
    if u_upper.startswith("A ") or u_upper.startswith("A-") or u_upper.startswith("A+"):
        result["canonical_outcome"] = "away"
        v1, v2 = _parse_line(u)
        result["line_value"] = v1
        result["line_value2"] = v2
        return result

    # ── Half Time / Full Time (umid=5) ──────────────────────────────────────
    # Usn format: 'HT/FT' e.g. '1/1', '1/X', 'X/2'
    # 1=home, X=draw, 2=away for both halves
    if '/' in u and len(u) <= 3:
        result['canonical_outcome'] = u_upper   # keep as-is: '1/1', '1/X' etc.
        return result

    # ── Unmapped — raw_outcome still stored ──────────────────────────────────
    return result