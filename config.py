import os
import re
from typing import Dict, List, Pattern, Any

import yaml


def _compile_pattern(entry: Any) -> re.Pattern:
    if isinstance(entry, dict):
        pattern = entry.get("regex") or entry.get("pattern")
        flags_str = entry.get("flags", "I")
    else:
        pattern = str(entry)
        flags_str = "I"
    flags = 0
    for part in str(flags_str).split("|"):
        part = part.strip()
        if not part:
            continue
        flags |= getattr(re, part, 0)
    return re.compile(pattern, flags)


def load_patterns(path: str | None = None) -> Dict[str, List[Pattern]]:
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "patterns.yml")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    compiled: Dict[str, List[Pattern]] = {}
    for key, items in raw.items():
        compiled[key] = [_compile_pattern(item) for item in (items or [])]
    return compiled


PATTERNS = load_patterns()

