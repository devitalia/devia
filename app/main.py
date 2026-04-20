import logging
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.comet_ddt import (
    delete_comet_ddt_import,
    list_comet_ddt_imports,
    sync_comet_ddt,
)
from app.config import settings
from app.email_ingest import (
    delete_processed_message,
    import_new_messages,
    list_processed_messages,
    replay_sonepar_messages,
)

openapi_tags = [
    {"name": "SYSTEM", "description": "Endpoint di servizio dell'applicazione."},
    {"name": "INTRANET", "description": "Importazioni e stato integrazioni Intranet (COMET/email)."},
    {"name": "EAGLE", "description": "Endpoint dedicati al cliente EAGLE."},
]

app = FastAPI(title=settings.app_name, openapi_tags=openapi_tags)
logger = logging.getLogger("devia.scheduler")


class EchoPayload(BaseModel):
    message: str


def _status_code_for_sync_status(status: str) -> int:
    if status in {"missing_comet_credentials", "missing_mail_credentials", "no_rules"}:
        return 503
    if status in {"imap_connection_error", "imap_search_error"}:
        return 502
    return 500


def _raise_if_sync_problem(component: str, result: dict) -> None:
    status = str(result.get("status") or "ok")
    if status == "ok":
        return
    raise HTTPException(
        status_code=_status_code_for_sync_status(status),
        detail={
            "component": component,
            "status": status,
            "result": result,
        },
    )


def _require_api_token(
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    expected = (settings.intranet_api_token or "").strip()
    if not expected:
        raise HTTPException(status_code=500, detail="api_token_not_configured")

    provided = (token or "").strip()
    if not provided and authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()

    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid_api_token")


def _parse_iso_date_or_400(value: str, field: str) -> datetime.date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid_{field}_format_use_yyyy_mm_dd") from exc


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["SYSTEM"])
def health() -> dict[str, str]:
    return {"ping": "pong"}


@app.get("/getddtdevtec", tags=["INTRANET"])
def getddtdevtec(_: None = Depends(_require_api_token)) -> dict:
    result = sync_comet_ddt()
    _raise_if_sync_problem("comet", result)
    return result


@app.get("/getddtdevtec/initial-import", tags=["INTRANET"])
def getddtdevtec_initial_import(_: None = Depends(_require_api_token)) -> dict[str, dict | str]:
    up_to_day = (datetime.utcnow() - timedelta(days=1)).date()
    comet_result = sync_comet_ddt(date_to=up_to_day)
    email_result = import_new_messages(date_to=up_to_day)
    _raise_if_sync_problem("comet", comet_result)
    _raise_if_sync_problem("email", email_result)
    return {
        "up_to_day": up_to_day.isoformat(),
        "comet": comet_result,
        "email": email_result,
    }


@app.get("/getddtdevtec/daily-sync", tags=["INTRANET"])
def getddtdevtec_daily_sync(_: None = Depends(_require_api_token)) -> dict[str, dict | str]:
    target_day = (datetime.utcnow() - timedelta(days=1)).date()
    comet_result = sync_comet_ddt(date_from=target_day, date_to=target_day)
    email_result = import_new_messages(date_from=target_day, date_to=target_day)
    _raise_if_sync_problem("comet", comet_result)
    _raise_if_sync_problem("email", email_result)
    return {
        "target_day": target_day.isoformat(),
        "comet": comet_result,
        "email": email_result,
    }


@app.get("/getddtdevtec/comet/state", tags=["INTRANET"])
def getddtdevtec_comet_state(_: None = Depends(_require_api_token)) -> dict:
    return list_comet_ddt_imports()


@app.delete("/getddtdevtec/comet/state/{progressive_id}", tags=["INTRANET"])
def delete_getddtdevtec_comet_state(progressive_id: int, _: None = Depends(_require_api_token)) -> dict:
    return delete_comet_ddt_import(progressive_id)


@app.get("/getddtdevtec/state", tags=["INTRANET"])
def getddtdevtec_state(_: None = Depends(_require_api_token)) -> dict:
    return list_processed_messages()


@app.get("/getddtdevtec/email/sync", tags=["INTRANET"])
def getddtdevtec_email_sync(_: None = Depends(_require_api_token)) -> dict:
    result = import_new_messages()
    _raise_if_sync_problem("email", result)
    return result


@app.get("/getddtdevtec/email/sonepar/replay", tags=["INTRANET"])
def getddtdevtec_email_sonepar_replay(
    _: None = Depends(_require_api_token),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    dry_run: bool = Query(default=True),
    fetch_limit: int = Query(default=2000, ge=1, le=10000),
) -> dict[str, dict | str | bool | int | list]:
    now = datetime.utcnow().date()
    start = (now - timedelta(days=30)) if not date_from else _parse_iso_date_or_400(date_from, "date_from")
    end = (now - timedelta(days=1)) if not date_to else _parse_iso_date_or_400(date_to, "date_to")
    result = replay_sonepar_messages(
        date_from=start,
        date_to=end,
        dry_run=dry_run,
        fetch_limit=fetch_limit,
    )
    _raise_if_sync_problem("email_sonepar_replay", result)
    return result


@app.delete("/getddtdevtec/state/{progressive_id}", tags=["INTRANET"])
def delete_getddtdevtec_state(progressive_id: int, _: None = Depends(_require_api_token)) -> dict:
    return delete_processed_message(progressive_id)


@app.post("/features/echo", tags=["EAGLE"])
def eagle_features_echo(payload: EchoPayload) -> dict[str, str]:
    return {"echo": payload.message}


@app.get("/eagle/health", tags=["EAGLE"])
def eagle_health() -> dict[str, str]:
    return {"client": "eagle", "status": "ok"}


@app.post("/eagle/echo", tags=["EAGLE"])
def eagle_echo(payload: EchoPayload) -> dict[str, str]:
    return {"echo": payload.message}
