"""dot photo processing library."""

__version__ = "0.4.0"


class DotPhotoError(Exception):
    """An error with a machine-readable code and a hint for the user."""

    def __init__(self, code: str, message: str, hint: str = "", exit_code: int = 5):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code

    def to_json(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}
