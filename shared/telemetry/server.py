from __future__ import annotations

import socket
from prometheus_client import start_http_server


def start_metrics_http_server(port: int) -> None:
    """Start a background HTTP server for Prometheus scrape.

    If port <= 0, does nothing.
    """
    if not port or int(port) <= 0:
        return
    # start_http_server is non-blocking
    start_http_server(int(port))
