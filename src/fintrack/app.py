"""HTTP API plus the built React app. Served on 127.0.0.1 only."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from . import items, reports, sync
from .config import Settings
from .db import connect, open_db
from .edits import InvalidEdit, UnknownTransaction, edit_transaction
from .enrich import enrich_all
from .plaid import PlaidClient, PlaidError, PlaidNotConfigured
from .scheduler import Scheduler

log = logging.getLogger(__name__)

FRONTEND_MISSING = """<!doctype html><meta charset="utf-8"><title>Fintrack</title>
<body style="font: 15px/1.6 -apple-system, 'PingFang SC', sans-serif; max-width: 560px; margin: 80px auto; padding: 0 16px">
<h1 style="font-size: 20px">前端还没有构建</h1>
<p>在项目目录运行下面两条命令，然后刷新本页：</p>
<pre style="background: #f2f2f0; padding: 12px; border-radius: 8px">npm --prefix web install
npm --prefix web run build</pre></body>"""


class LinkTokenRequest(BaseModel):
    item_id: int | None = None  # set to repair an existing Item in update mode


class ExchangeRequest(BaseModel):
    public_token: str
    institution_id: str | None = None
    institution_name: str | None = None


class TransactionEdit(BaseModel):
    # Only the fields sent are changed; sending null reverts that field.
    category_id: str | None = None
    note: str | None = None


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    db = connect(request.app.state.settings.db_path)
    try:
        yield db
    finally:
        db.close()


def get_plaid(request: Request) -> PlaidClient:
    return request.app.state.plaid_factory()


Db = Annotated[sqlite3.Connection, Depends(get_db)]
Plaid = Annotated[PlaidClient, Depends(get_plaid)]


def create_app(
    settings: Settings,
    plaid_factory: Callable[[], PlaidClient] | None = None,
    *,
    run_scheduler: bool = True,
) -> FastAPI:
    db = open_db(settings.db_path)  # apply migrations, then re-derive categories with the current rules
    enrich_all(db)
    db.close()
    make_plaid = plaid_factory or (lambda: PlaidClient.from_settings(settings))
    scheduler = Scheduler(settings.db_path, make_plaid) if run_scheduler else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if scheduler:
            scheduler.start()
        try:
            yield
        finally:
            if scheduler:
                scheduler.stop()

    app = FastAPI(title="Fintrack", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.plaid_factory = make_plaid
    # Answer only requests addressed to localhost, so a DNS-rebinding web page can't read the API.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    def error(status_code: int) -> Callable[[Request, Exception], Any]:
        async def handler(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=status_code)

        return handler

    app.add_exception_handler(PlaidNotConfigured, error(503))
    app.add_exception_handler(PlaidError, error(502))
    app.add_exception_handler(UnknownTransaction, error(404))
    app.add_exception_handler(InvalidEdit, error(422))

    @app.exception_handler(items.UnknownItem)
    async def unknown_item(request: Request, exc: items.UnknownItem) -> JSONResponse:
        return JSONResponse({"detail": f"item {exc} not found"}, status_code=404)

    @app.exception_handler(items.MissingAccessToken)
    async def missing_token(request: Request, exc: items.MissingAccessToken) -> JSONResponse:
        detail = f"item {exc} 的 access token 不在 Keychain 里，只能重新连接这家银行"
        return JSONResponse({"detail": detail}, status_code=409)

    # Background jobs run after the response is sent and open their own connection.
    def sync_job(client: PlaidClient, triggered_by: str, item_ids: list[int] | None = None) -> None:
        db = connect(settings.db_path)
        try:
            sync.run_sync(db, client, triggered_by=triggered_by, item_ids=item_ids)
        except sync.SyncInProgress:
            log.info("sync already running; skipped %s request", triggered_by)
        finally:
            db.close()

    def backfill_job(client: PlaidClient, item_id: int) -> None:
        db = connect(settings.db_path)
        try:
            sync.sync_new_item(db, client, item_id)
        finally:
            db.close()

    @app.get("/api/status")
    def status(db: Db) -> dict[str, Any]:
        try:
            make_plaid()
            plaid_configured = True
        except PlaidNotConfigured:
            plaid_configured = False
        item_rows = db.execute(
            """
            SELECT id, institution_name, status, transactions_status, last_synced_at, last_error
            FROM items ORDER BY id
            """
        ).fetchall()
        last_run = db.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
        if last_run is not None:
            last_run = {**dict(last_run), "summary": json.loads(last_run["summary"] or "null")}
        last_success_at = db.execute(
            "SELECT MAX(finished_at) FROM sync_runs WHERE status IN ('success', 'partial')"
        ).fetchone()[0]
        return {
            "env": settings.env,
            "plaid_configured": plaid_configured,
            "syncing": sync.is_running(),
            "items": [dict(row) for row in item_rows],
            "last_run": last_run,
            "last_success_at": last_success_at,
        }

    @app.post("/api/link/token")
    def link_token(body: LinkTokenRequest, db: Db, plaid: Plaid) -> dict[str, str]:
        return {"link_token": items.create_link_token(db, plaid, body.item_id)}

    @app.post("/api/link/exchange")
    def link_exchange(body: ExchangeRequest, background: BackgroundTasks, db: Db, plaid: Plaid) -> dict[str, int]:
        item_id = items.save_item(db, plaid, body.public_token, body.institution_id, body.institution_name)
        background.add_task(backfill_job, plaid, item_id)
        return {"item_id": item_id}

    @app.post("/api/items/{item_id}/reconnected")
    def item_reconnected(item_id: int, background: BackgroundTasks, db: Db, plaid: Plaid) -> dict[str, int]:
        items.mark_reconnected(db, item_id)
        background.add_task(sync_job, plaid, "manual", [item_id])
        return {"item_id": item_id}

    @app.post("/api/sync", status_code=202)
    def start_sync(background: BackgroundTasks, plaid: Plaid) -> dict[str, bool]:
        if sync.is_running():
            raise HTTPException(409, "同步正在进行中")
        background.add_task(sync_job, plaid, "manual")
        return {"started": True}

    @app.get("/api/accounts")
    def list_accounts(db: Db) -> list[dict[str, Any]]:
        rows = db.execute(
            """
            SELECT a.id, a.item_id, a.name, a.official_name, a.mask, a.type, a.subtype, a.currency,
                   a.current_cents, a.available_cents, a.limit_cents, a.balance_as_of,
                   i.institution_name
            FROM accounts a JOIN items i ON i.id = a.item_id
            ORDER BY i.id, a.type != 'depository', a.name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    @app.get("/api/overview")
    def get_overview(db: Db) -> dict[str, Any]:
        return reports.overview(db, date.today())

    @app.get("/api/activity")
    def get_activity(
        db: Db,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        before: str | None = None,
        before_id: int | None = None,
        q: str | None = None,
        account_id: int | None = None,
        category_id: str | None = None,
        flow_type: Literal["income", "expense", "transfer"] | None = None,
    ) -> dict[str, Any]:
        cursor = (before, before_id) if before is not None and before_id is not None else None
        return reports.activity(
            db, limit=limit, before=cursor, query=q, account_id=account_id, category_id=category_id, flow_type=flow_type
        )

    @app.get("/api/categories")
    def list_categories(db: Db) -> list[dict[str, Any]]:
        return reports.categories(db)

    @app.patch("/api/transactions/{transaction_id}")
    def edit(transaction_id: int, body: TransactionEdit, db: Db) -> dict[str, Any] | None:
        edit_transaction(db, transaction_id, {field: getattr(body, field) for field in body.model_fields_set})
        return reports.ledger_row(db, transaction_id)

    # Everything that isn't the API is the React app: real files from the build, otherwise
    # index.html so client-side routes like /activity load too.
    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        dist = settings.web_dist.resolve()
        if not (dist / "index.html").exists():
            return HTMLResponse(FRONTEND_MISSING, status_code=503)
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        return FileResponse(dist / "index.html")

    return app
