"""后端启动脚本 — 本机 Python 无 venv/ensurepip，依赖装在 backend/.deps（pip --target）

用法：python run.py [--port 8000]
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEPS = BASE / ".deps"
if DEPS.exists():
    sys.path.insert(0, str(DEPS))
sys.path.insert(0, str(BASE))

import uvicorn

if __name__ == "__main__":
    port = 8000
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="info")
