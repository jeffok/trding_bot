from __future__ import annotations

import os
import socket


def get_instance_id(default: str = "") -> str:
    """Return instance id for service_status primary key.

    Priority:
    1) explicit env INSTANCE_ID
    2) passed default (if non-empty)
    3) hostname:pid
    """
    env = os.getenv("INSTANCE_ID", "").strip()
    if env:
        return env
    if default:
        return default
    host = socket.gethostname()
    pid = os.getpid()
    return f"{host}:{pid}"
