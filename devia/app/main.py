from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import get_settings
from .db import DB
from .instructions import load_instructions

settings = get_settings()
app = FastAPI(title=settings.name)


class ChatIn(BaseModel):
    user: dict
    message: str
    conversation_id: str | None = None


@app.get("/health")
def health():
    # verifica rapida: istruzioni + db dsn presente
    instr = load_instructions(settings)
    return {
        "ok": True,
        "service": settings.name,
        "has_project_md": bool(instr["project_md"].strip()),
        "has_policy_md": bool(instr["policy_md"].strip()),
        "db_configured": bool(settings.db_dsn),
    }


@app.get("/db/ping")
def db_ping():
    if not settings.db_dsn:
        raise HTTPException(status_code=500, detail="DEVIA_DB_DSN non configurato")
    db = DB(settings.db_dsn)
    return {"ok": db.ping()}


@app.post("/chat")
def chat(payload: ChatIn):
    instr = load_instructions(settings)

    # Demo: risponde mostrando che ha caricato istruzioni.
    # Qui poi metteremo:
    # - lettura DB impostazioni
    # - tool/action proposal
    msg = payload.message.strip()

    if not msg:
        raise HTTPException(status_code=422, detail="Messaggio vuoto")

    return {
        "type": "message",
        "assistant": settings.name,
        "message": (
            f"DevIA operativo. Ho caricato istruzioni progetto: "
            f"{'SI' if instr['project_md'].strip() else 'NO'}, "
            f"policy: {'SI' if instr['policy_md'].strip() else 'NO'}. "
            f"Mi hai scritto: {msg}"
        ),
    }
