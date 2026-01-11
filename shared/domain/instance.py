from __future__ import annotations

import os
import socket


def get_instance_id(*args: str) -> str:
    """Return instance id for service_status primary key.

    Backward-compatible call styles:
    - get_instance_id(default)
    - get_instance_id(service, default)

    Priority:
    1) explicit env INSTANCE_ID
    2) passed default (if non-empty)
    3) hostname:pid (or service:hostname:pid)
    """
    service = ""
    default = ""
    if len(args) == 1:
        default = args[0] or ""
    elif len(args) >= 2:
        service = args[0] or ""
        default = args[1] or ""

    env = os.getenv("INSTANCE_ID", "").strip()
    if env:
        return env
    if default:
        return default

    host = socket.gethostname()
    pid = os.getpid()
    if service:
        return f"{service}:{host}:{pid}"
    return f"{host}:{pid}"
