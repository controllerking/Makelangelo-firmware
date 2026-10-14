"""Startup-only robot configuration. No shell evaluation or runtime discovery."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
KEYS = {"DRAWY_ROBOT_HOST", "DRAWY_ROBOT_PORT", "DRAWY_ROBOT_PAIRING_KEY"}


@dataclass(frozen=True)
class RobotConfig:
    host: str = "drawy.local"
    port: int = 9999
    token: str = field(default="", repr=False)


def load_robot_config(path=ENV_FILE, environ=None):
    values = {}
    path = Path(path)
    if path.exists():
        for number, raw in enumerate(path.read_text().splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"): continue
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or key not in KEYS or key in values:
                raise ValueError(f"Invalid or duplicate robot setting in .env at line {number}")
            if value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError(f"Unclosed quote in .env at line {number}")
                value = value[1:-1]
            values[key] = value
    environment = os.environ if environ is None else environ
    values.update({key:environment[key] for key in KEYS if key in environment})
    host = values.get("DRAWY_ROBOT_HOST", "").strip()
    token = values.get("DRAWY_ROBOT_PAIRING_KEY", "").strip()
    port = values.get("DRAWY_ROBOT_PORT", "9999")
    if not host or len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9_.:\-]+", host):
        raise ValueError("Set DRAWY_ROBOT_HOST in .env to the robot hostname or IP")
    if not token or len(token) > 256 or any(c.isspace() for c in token):
        raise ValueError("Set DRAWY_ROBOT_PAIRING_KEY in .env to the device pairing key")
    try: port = int(port)
    except (ValueError, TypeError): raise ValueError("DRAWY_ROBOT_PORT must be 1–65535") from None
    if not 1 <= port <= 65535: raise ValueError("DRAWY_ROBOT_PORT must be 1–65535")
    return RobotConfig(host, port, token)
