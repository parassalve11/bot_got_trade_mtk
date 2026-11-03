class Reject(Exception):
    """A deterministic policy/broker rejection; do not automatically resend."""


class Retryable(Exception):
    """Known pre-send failure, safe to retry while the event is fresh."""


class Uncertain(Exception):
    """An operation may have reached the broker. Reconcile; NEVER blindly retry."""


class SafetyError(Exception):
    """Ownership/account/protection anomaly requiring an operator review."""
