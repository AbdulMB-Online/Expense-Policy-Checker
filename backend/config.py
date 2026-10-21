"""Project paths, independent of the process working directory."""

from hashlib import sha256
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_ROOT.parent
ENGINE_VERSION = sha256(
    b"".join(path.read_bytes() for path in sorted((BACKEND_ROOT / "rules").glob("*.py")))
).hexdigest()
