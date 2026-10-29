#!/usr/bin/env python3
"""Start the NordRouter Web UI server."""
import os
import sys
from pathlib import Path

# Auto-activate project venv if not already active
_project_root = Path(__file__).resolve().parent.parent
_venv_python = _project_root / ".venv" / "bin" / "python3"
if _venv_python.exists() and sys.executable != str(_venv_python):
    os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)

# Ensure project root is on sys.path so `web.backend.app` resolves
sys.path.insert(0, str(_project_root))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "web.backend.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("WEB_PORT", "8090")),
        reload=True,
    )