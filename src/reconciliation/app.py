"""Layer 7: UI (server-rendered via FastAPI + Jinja2).

Phase 0: placeholder home page only, to prove the scaffold runs end-to-end.
Real screens (run list, run detail, row detail, manual match) land in
Phases 4-5.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="Reconciliation Ledger")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"message": "Reconciliation Ledger — scaffold running."},
    )
