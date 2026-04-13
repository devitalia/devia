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

openapi_tags = [
    {"name": "SYSTEM", "description": "Endpoint di servizio dell'applicazione."},
    {"name": "INTRANET", "description": "Importazioni e stato integrazioni Intranet (COMET/email)."},
    {"name": "EAGLE", "description": "Endpoint dedicati al cliente EAGLE."},
]

app = FastAPI(title=settings.app_name, openapi_tags=openapi_tags)


class EchoPayload(BaseModel):
    message: str


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["SYSTEM"])
def health() -> dict[str, str]:
    return {"ping": "pong"}


@app.get("/getddtdevtec", tags=["INTRANET"])
def getddtdevtec() -> dict:
    return sync_comet_ddt()


@app.get("/getddtdevtec/comet/state", tags=["INTRANET"])
def getddtdevtec_comet_state() -> dict:
    return list_comet_ddt_imports()


@app.delete("/getddtdevtec/comet/state/{progressive_id}", tags=["INTRANET"])
def delete_getddtdevtec_comet_state(progressive_id: int) -> dict:
    return delete_comet_ddt_import(progressive_id)


@app.get("/getddtdevtec/state", tags=["INTRANET"])
def getddtdevtec_state() -> dict:
    return list_processed_messages()


@app.get("/getddtdevtec/email/sync", tags=["INTRANET"])
def getddtdevtec_email_sync() -> dict:
    return import_new_messages()


@app.delete("/getddtdevtec/state/{progressive_id}", tags=["INTRANET"])
def delete_getddtdevtec_state(progressive_id: int) -> dict:
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
