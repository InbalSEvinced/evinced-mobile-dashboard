"""
FastAPI server for the Mobile Products Dashboard.

Endpoints:
  GET  /              → serves the generated HTML
  GET  /dashboard.pdf → serves the generated PDF (if present)
  POST /refresh       → triggers the refresh pipeline (Cloud Run IAM enforces auth)
  GET  /healthz       → liveness probe for Cloud Run
"""
import os
import subprocess
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

BASE = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR") or (BASE / "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HTML_PATH = OUTPUT_DIR / "mobile-products-dashboard.html"
PDF_PATH = OUTPUT_DIR / "mobile-products-dashboard.pdf"

app = FastAPI(title="Mobile Products Dashboard")
_refresh_lock = threading.Lock()


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.get("/", response_class=HTMLResponse)
def index():
    if not HTML_PATH.exists():
        return HTMLResponse(
            "<h1>Dashboard not yet initialized</h1>"
            "<p>POST /refresh (authenticated) to generate the first snapshot.</p>",
            status_code=503,
        )
    return HTMLResponse(HTML_PATH.read_text())


@app.get("/dashboard.pdf")
def pdf():
    if not PDF_PATH.exists():
        raise HTTPException(status_code=404, detail="PDF not generated yet")
    return FileResponse(
        PDF_PATH,
        media_type="application/pdf",
        filename="mobile-products-dashboard.pdf",
    )


@app.post("/refresh")
def refresh():
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Refresh already in progress")
    try:
        env = {**os.environ, "OUTPUT_DIR": str(OUTPUT_DIR)}
        result = subprocess.run(
            ["python3", "refresh_all.py"],
            cwd=str(BASE),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        tail = (result.stdout or "")[-2000:]
        if result.returncode != 0:
            err = (result.stderr or "")[-2000:]
            raise HTTPException(status_code=500, detail=f"Refresh failed:\n{err}")
        return {"status": "ok", "output": tail}
    finally:
        _refresh_lock.release()
