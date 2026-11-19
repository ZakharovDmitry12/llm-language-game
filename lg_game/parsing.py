"""Conservative, deterministic output parsing without additional model calls."""
import json
import math
import re
from .prompts import OFFERS

def parse_offer(text):
    s = (text or "").strip()
    if not re.fullmatch(r"\d{1,2}", s):
        return None
    value = int(s)
    return value if value in OFFERS else None

def parse_decision(text):
    s = (text or "").strip()
    return int(s) if s in ("0", "1") else None

def _parse_forecast_numbers(s):
    try:
        values = json.loads(s)
    except (ValueError, TypeError):
        if not re.fullmatch(r"[\d.eE+\-,\s]+", s):
            return None
        try:
            values = [float(v) for v in re.split(r"[,\s]+", s) if v]
        except ValueError:
            return None
    if not isinstance(values, list) or len(values) != 9:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        return None
    return [float(v) for v in values]

def parse_forecast(text):
    # Accept a complete numeric response, or exactly nine numbers in the final
    # nonempty line after an explanation. Do not extract from tables or prose.
    s = (text or "").strip()
    result = _parse_forecast_numbers(s)
    if result is not None:
        return result
    lines = [line.strip() for line in s.splitlines() if line.strip()]
    if not lines:
        return None
    last = lines[-1]
    if last.startswith('**') and last.endswith('**') and len(last) >= 4:
        last = last[2:-2].strip()
    return _parse_forecast_numbers(last)

def parse_offer_language(text):
    s = (text or "").strip()
    if s.startswith('**') and s.endswith('**') and len(s) >= 4:
        s = s[2:-2].strip()
    match = re.fullmatch(r"(10|20|30|40|50|60|70|80|90)(?:\s+points?)?\s*[,;:\s]+\s*(English|Russian)", s, re.I)
    if match:
        return int(match.group(1)), match.group(2).title()
    match = re.fullmatch(r"(English|Russian)\s*[,;:\s]+\s*(10|20|30|40|50|60|70|80|90)(?:\s+points?)?", s, re.I)
    if match:
        return int(match.group(2)), match.group(1).title()
    return None
