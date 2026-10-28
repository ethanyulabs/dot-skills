"""dot arc: drive the user's Arc browser in a named space (AppleScript for spaces and tabs, CDP for pages)."""

__version__ = "0.5.0"


class DotArcError(Exception):
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
