"""Load ``.env`` without pulling in a dependency.

``run.sh`` already sources the file, but the app is also started in other
ways — ``uvicorn app.main:app`` from inside ``backend/``, a debugger, or an
IDE run configuration. In those cases the key would be missing and the
system would silently fall back to the extractive engine, which looks like
the DeepSeek backend simply being slow. Loading the file here removes that
failure mode.

The parser handles the subset of the ``.env`` format the project uses:
``KEY=value`` lines, ``#`` comments, optional ``export`` prefix and optional
single or double quotes around the value. Values already present in the
environment always win, so ``run.sh``'s exported values are not overwritten.
"""

from __future__ import annotations

import os
from pathlib import Path

# The repository root: backend/app/envfile.py -> backend/app -> backend -> root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_env(path: Path | None = None) -> dict[str, str]:
    """Parse the ``.env`` file and return the values it defines.

    Values already set in the environment are left untouched, so an
    explicitly exported variable always overrides the file.
    """
    target = path or ENV_FILE
    loaded: dict[str, str] = {}
    if not target.is_file():
        return loaded

    try:
        content = target.read_text(encoding="utf-8")
    except OSError:
        return loaded

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = _strip_quotes(value.strip())
        if not key:
            continue
        loaded[key] = value
        # Do not override a value that the caller set deliberately.
        os.environ.setdefault(key, value)
    return loaded


load_env()
