"""Client address for rate limiting, for a service right behind Railway's proxy (no CDN).

Railway's edge proxy sets ``X-Real-IP`` itself and does not pass on a value sent by the
client. ``X-Forwarded-For`` is not used: with ``--forwarded-allow-ips '*'`` uvicorn takes
``request.client`` from its leftmost entry, which the client controls.
"""

import ipaddress

from fastapi import Request

REAL_IP_HEADER = "x-real-ip"


def client_ip(request: Request) -> str:
    """``X-Real-IP`` when it holds an IP address, otherwise the connection address."""
    values = request.headers.getlist(REAL_IP_HEADER)
    if values:
        # The proxy's own header comes last should a client value ever slip through.
        try:
            return str(ipaddress.ip_address(values[-1].strip()))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"
