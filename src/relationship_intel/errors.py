"""Cross-cutting exceptions."""


class NotConfiguredError(RuntimeError):
    """A source or adapter is missing required configuration (e.g., API key)."""
