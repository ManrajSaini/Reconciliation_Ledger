"""Layer 7: UI (server-rendered via FastAPI + Jinja2).

Phase 4: run list (upload + trigger), run detail (bucketed results), and
row detail (field-by-field diff) -- read/trigger-only.
Phase 5: manual resolution -- for an unmatched ledger row, show ranked
heuristic candidates plus every other unmatched statement row, and let a
human confirm a pairing or declare "no pair."

The DB engine is provided via FastAPI dependency injection (get_db_engine)
rather than created at module import time -- importing this module (e.g.
from a test) must never have the side effect of touching the real
data/reconciliation.db file on disk.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine

from reconciliation import repository as repo
from reconciliation.comparison import compare
from reconciliation.db import get_engine
from reconciliation.orchestration import STATEMENT_SOURCE, build_run_detail_view, run_reconciliation

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="Reconciliation Ledger")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_engine: Engine | None = None


def get_db_engine() -> Engine:
    """Lazily creates the real on-disk engine on first use. Tests override
    this dependency (app.dependency_overrides[get_db_engine]) to point at an
    isolated in-memory database instead."""
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def display_value(value):
    """Side/TxnStatus are (str, Enum) mixins, whose default str() gives the
    ugly 'Side.BUY' repr instead of 'BUY' -- render their .value instead.
    Decimals coming back from SQLite's Numeric column are padded with
    trailing zeros to a fixed scale (e.g. Decimal('5.0000000000')) -- this
    is a storage-roundtrip artifact, not a real precision difference, so
    strip it for display. Decimal.normalize() does this but switches to
    scientific notation for round numbers (3400 -> '3.4E+3'), so trailing
    zeros are stripped from the fixed-point string instead."""
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Decimal):
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    return value


templates.env.filters["display"] = display_value


@app.get("/")
def run_list(request: Request, engine: Engine = Depends(get_db_engine)):
    with engine.connect() as conn:
        runs = repo.list_runs(conn)
    return templates.TemplateResponse(request=request, name="run_list.html", context={"runs": runs})


@app.post("/runs")
async def start_run(
    ledger_file: UploadFile | None = None,
    statement_file: UploadFile | None = None,
    engine: Engine = Depends(get_db_engine),
):
    ledger_content = await ledger_file.read() if ledger_file and ledger_file.filename else None
    statement_content = (
        await statement_file.read() if statement_file and statement_file.filename else None
    )

    with engine.connect() as conn:
        summary = run_reconciliation(
            conn,
            ledger_filename=ledger_file.filename if ledger_content else None,
            ledger_content=ledger_content,
            statement_filename=statement_file.filename if statement_content else None,
            statement_content=statement_content,
        )

    return RedirectResponse(url=f"/runs/{summary.run_id}", status_code=303)


@app.get("/runs/{run_id}")
def run_detail(request: Request, run_id: int, engine: Engine = Depends(get_db_engine)):
    with engine.connect() as conn:
        view = build_run_detail_view(conn, run_id)

    if view is None:
        return templates.TemplateResponse(
            request=request, name="not_found.html", context={}, status_code=404
        )

    return templates.TemplateResponse(
        request=request, name="run_detail.html", context={"view": view}
    )


@app.get("/runs/{run_id}/pair/{left_source}/{left_external_id}")
def row_detail(
    request: Request,
    run_id: int,
    left_source: str,
    left_external_id: str,
    engine: Engine = Depends(get_db_engine),
):
    with engine.connect() as conn:
        view = build_run_detail_view(conn, run_id)
        if view is None:
            return templates.TemplateResponse(
                request=request, name="not_found.html", context={}, status_code=404
            )

        pair_view = next(
            (
                p
                for p in (view.agreeing_pairs + view.differing_pairs)
                if p.left.source == left_source and p.left.external_id == left_external_id
            ),
            None,
        )
        if pair_view is None:
            return templates.TemplateResponse(
                request=request, name="not_found.html", context={}, status_code=404
            )

        result = compare(pair_view.left, pair_view.right)
        left_history = repo.get_version_history(conn, left_source, left_external_id)
        right_history = repo.get_version_history(
            conn, pair_view.right.source, pair_view.right.external_id
        )

    return templates.TemplateResponse(
        request=request,
        name="row_detail.html",
        context={
            "run_id": run_id,
            "result": result,
            "left_history": left_history,
            "right_history": right_history,
        },
    )


@app.get("/runs/{run_id}/resolve/{left_source}/{left_external_id}")
def resolve_row(
    request: Request,
    run_id: int,
    left_source: str,
    left_external_id: str,
    engine: Engine = Depends(get_db_engine),
):
    with engine.connect() as conn:
        view = build_run_detail_view(conn, run_id)
        if view is None:
            return templates.TemplateResponse(
                request=request, name="not_found.html", context={}, status_code=404
            )

        unmatched_row = next(
            (
                u
                for u in view.unmatched_left
                if u.txn.source == left_source and u.txn.external_id == left_external_id
            ),
            None,
        )
        if unmatched_row is None:
            return templates.TemplateResponse(
                request=request, name="not_found.html", context={}, status_code=404
            )

        candidate_ids = {c.right.external_id for c in unmatched_row.candidates}
        other_unmatched_right = tuple(
            t for t in view.unmatched_right if t.external_id not in candidate_ids
        )

    return templates.TemplateResponse(
        request=request,
        name="resolve.html",
        context={
            "run_id": run_id,
            "row": unmatched_row,
            "other_unmatched_right": other_unmatched_right,
        },
    )


@app.post("/runs/{run_id}/resolve/{left_source}/{left_external_id}")
def submit_resolution(
    run_id: int,
    left_source: str,
    left_external_id: str,
    action: str = Form(...),
    right_external_id: str | None = Form(None),
    engine: Engine = Depends(get_db_engine),
):
    with engine.connect() as conn:
        if action == "match":
            repo.record_manual_match(
                conn, left_source, left_external_id, STATEMENT_SOURCE, right_external_id
            )
        elif action == "no_pair":
            repo.record_manual_no_pair(conn, left_source, left_external_id)

    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
