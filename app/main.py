from fastapi import FastAPI
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
)

app = FastAPI(title=settings.app_name)


class EchoPayload(BaseModel):
    message: str


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict[str, str]:
    return {"ping": "pong"}


@app.get("/getddtdevtec")
def getddtdevtec() -> dict:
    return sync_comet_ddt()


@app.get("/getddtdevtec/comet/state")
def getddtdevtec_comet_state() -> dict:
    return list_comet_ddt_imports()


@app.delete("/getddtdevtec/comet/state/{progressive_id}")
def delete_getddtdevtec_comet_state(progressive_id: int) -> dict:
    return delete_comet_ddt_import(progressive_id)


@app.get("/getddtdevtec/state")
def getddtdevtec_state() -> dict:
    return list_processed_messages()


@app.get("/getddtdevtec/email/sync")
def getddtdevtec_email_sync() -> dict:
    return import_new_messages()


@app.delete("/getddtdevtec/state/{progressive_id}")
def delete_getddtdevtec_state(progressive_id: int) -> dict:
    return delete_processed_message(progressive_id)


@app.post("/features/echo")
def features_echo(payload: EchoPayload) -> dict[str, str]:
    return {"echo": payload.message}
