"""Errors whose message is written for the person running Bridge."""


class BridgeError(RuntimeError, ValueError):
    """A failure with Korean guidance that is safe to show on the screen.

    It is both a RuntimeError and a ValueError so existing handlers keep catching it.
    """
