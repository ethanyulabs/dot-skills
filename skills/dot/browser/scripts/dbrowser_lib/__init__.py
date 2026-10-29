"""dot browser: drive the user's browser — Arc in a named space (AppleScript + CDP), Chrome or Edge in dot's own instance (CDP only)."""

__version__ = "0.6.0"


class DotBrowserError(Exception):
    """An error with a machine-readable code and a hint for the user."""

    def __init__(self, code: str, message: str, hint: str = "", exit_code: int = 5, payload: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code
        self.payload = dict(payload or {})  # extra top-level fields for the JSON line (spaces, candidates, checks)

    def to_json(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}
