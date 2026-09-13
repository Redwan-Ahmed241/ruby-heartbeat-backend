import sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
from main import app
from fastapi import Request

@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def catch_all(request: Request, full_path: str):
    return {
        "detail": "Path Inspector",
        "url_path": request.url.path,
        "full_path": full_path,
        "root_path": request.scope.get("root_path", ""),
        "raw_path": request.scope.get("raw_path", b"").decode("utf-8", errors="ignore"),
    }

