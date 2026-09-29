import re
from datetime import datetime


def parse(line: str) -> dict | None:
    if not isinstance(line, str):
        return None

    line = line.rstrip("\n").rstrip("\r")
    if not line:
        return None

    # Split into at most 5 parts by '|'
    parts = line.split("|")
    if len(parts) < 5:
        return None

    timestamp_raw = parts[0].strip()
    level = parts[1].strip()
    module = parts[2].strip()
    step_raw = parts[3].strip()
    message = "|".join(parts[4:]).strip()

    # Validate timestamp: ISO 8601 with Z
    ts_match = re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z",
        timestamp_raw,
    )
    if not ts_match:
        return None
    try:
        datetime(
            int(ts_match.group(1)),
            int(ts_match.group(2)),
            int(ts_match.group(3)),
            int(ts_match.group(4)),
            int(ts_match.group(5)),
            int(ts_match.group(6)),
        )
    except ValueError:
        return None

    # Validate level
    if not re.fullmatch(r"[A-Z]+", level):
        return None

    # Validate module (dotted identifier)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", module):
        return None

    # Validate step: step=<int>
    step_match = re.fullmatch(r"step=(\d+)", step_raw)
    if not step_match:
        return None
    step = int(step_match.group(1))

    if not message:
        return None

    return {
        "timestamp": timestamp_raw,
        "level": level,
        "module": module,
        "step": step,
        "message": message,
    }