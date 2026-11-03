import hmac
import time
from collections import deque
from ipaddress import ip_address, ip_network

from fastapi import HTTPException, Request


def authenticate_webhook(request: Request, token: str, settings):
    if not hmac.compare_digest(token.encode(), settings.webhook_token.get_secret_value().encode()):
        raise HTTPException(401, "unauthorized")
    # Intentionally ignore forwarding headers. The direct reverse proxy peer is trusted,
    # and Caddy checks TradingView's real source IP before proxying the request.
    try:
        peer = ip_address(request.client.host)
        allowed = any(peer in ip_network(network, strict=False) for network in settings.webhook_allowed_ips)
    except (ValueError, AttributeError):
        allowed = False
    if not allowed:
        raise HTTPException(403, "source_not_allowed")


def authenticate_admin(request: Request):
    expected = request.app.state.settings.admin_token.get_secret_value()
    actual = request.headers.get("authorization", "")
    if not hmac.compare_digest(actual.encode(), ("Bearer " + expected).encode()):
        raise HTTPException(401, "unauthorized")


class IntakeLimiter:
    """Single-process burst limiter; Caddy is still the public ingress boundary."""

    def __init__(self, limit=120, window=60):
        self.limit, self.window = limit, window
        self.timestamps = deque()

    def allow(self):
        now = time.monotonic()
        while self.timestamps and self.timestamps[0] <= now - self.window:
            self.timestamps.popleft()
        if len(self.timestamps) >= self.limit:
            return False
        self.timestamps.append(now)
        return True
