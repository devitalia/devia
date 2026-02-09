import logging
import os
import re
import urllib.error
import urllib.request

from typing import Any, Dict

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import Settings, get_settings
from .db import DB
from .instructions import list_repo_files, load_instructions, load_repo_code
from .llm import (
    answer_from_query_result,
    build_intent_prompt,
    classify_intent,
    classify_page_action,
    explain_action_result,
    explain_error_to_user,
    extract_leave_params,
    generate_sql_for_question,
    need_db_data,
    page_driven_plan,
    _call_llm,
    _generic_fallback_action,
    _message_label_overlap_score,
)
from .tts import synthesize_reply

logger = logging.getLogger(__name__)
if os.environ.get("DEVIA_DEBUG"):
    logging.basicConfig(level=logging.DEBUG)
else:
    logger.setLevel(logging.INFO)
settings = get_settings()
app = FastAPI(title=settings.name)

# Stato in memoria per azioni in attesa di conferma, indicizzate per conversation_id.
# Struttura: { conversation_id: {"intent": str, "params": dict, "original_message": str} }
PENDING_ACTIONS: dict[str, dict] = {}


def _build_message_response(
    message: str,
    client_action: str | None = None,
    action_id: str | None = None,
    action_index: int | None = None,
    action_sequence: list[str] | None = None,
    action_indices: list[int] | None = None,
    form_fill: dict | None = None,
    reasoning: str | None = None,
    auto_reapply: bool | None = None,
) -> dict:
    """
    Costruisce la risposta standard di DevIA.
    action_index / action_indices: progressivo nell'array inviato dal client (numero, niente id lunghi).
    """
    resp: dict = {
        "type": "message",
        "assistant": settings.name,
        "message": message,
    }
    if client_action:
        resp["client_action"] = client_action
    if action_id is not None:
        resp["action_id"] = action_id
    if action_index is not None:
        resp["action_index"] = action_index
    if action_sequence:
        resp["action_sequence"] = action_sequence
    if action_indices:
        resp["action_indices"] = action_indices
    if form_fill:
        resp["form_fill"] = form_fill
    if reasoning:
        resp["reasoning"] = reasoning
    if auto_reapply is not None:
        resp["auto_reapply"] = bool(auto_reapply)
    audio = synthesize_reply(settings, message)
    if audio:
        resp["audio"] = audio
    return resp


def _call_laravel_action(settings: Settings, user: dict, action: str, params: dict | None = None) -> dict | None:
    """
    Esegue una chiamata al tool Laravel corrispondente all'azione
    e restituisce sempre il JSON ricevuto (o None in caso di errore).
    """
    base = settings.laravel_base_url
    if not base:
        return None

    action = action.lower()
    if action == "timbra_entrata":
        endpoint = "/tools/timbra-entrata"
    elif action == "timbra_uscita":
        endpoint = "/tools/timbra-uscita"
    elif action == "prenota_ferie":
        endpoint = "/tools/prenota-ferie"
    elif action == "prenota_rol":
        endpoint = "/tools/prenota-rol"
    else:
        return None

    payload: dict = params or {}

    url = base.rstrip("/") + endpoint
    headers = {
        "Content-Type": "application/json",
        "X-Devia-User-Id": str(user.get("id") or user.get("user_id") or ""),
    }
    if settings.laravel_tool_token:
        headers["Authorization"] = f"Bearer {settings.laravel_tool_token}"

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=payload)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        return {
            "status": resp.status_code,
            "data": data,
        }
    except Exception as e:
        logger.warning("Chiamata azione Laravel fallita: %s", e)
        return None


def _check_llm_reachable(s: Settings) -> bool:
    """Verifica che l'API LLM risponda. Con Ollama: GET /api/tags; senza base_url (cloud) considera configurato = ok."""
    if not s.llm_base_url and not s.llm_api_key:
        return False
    if not s.llm_base_url:
        return True  # solo API key (cloud): non fare richiesta, considera ok se configurato
    base = s.llm_base_url.rstrip("/")
    url = (base[:-3] + "/api/tags") if base.endswith("/v1") else (base.split("/v1")[0] + "/api/tags")
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as _:
            return True
    except Exception as e:
        logger.debug("LLM check failed: %s", e)
        return False


class ChatIn(BaseModel):
    user: dict
    message: str
    conversation_id: str | None = None
    app_url: str | None = None  # URL base dell'intranet (es. http://localhost:37000) per link e API
    available_actions: list[dict] | None = None  # azioni esposte dalla pagina (id, label, active)
    form_fields: list[dict] | None = None  # campi form visibili (label, required, type) per compilazione intelligente


class TtsIn(BaseModel):
    text: str


def _is_confirmation(message: str) -> bool:
    """
    Rileva conferme semplici per eseguire un'azione già proposta.
    Esempi: "sì", "si", "prima sì", "ok procedi", "vai pure", "confermo".
    """
    lower = message.strip().lower()
    if lower in {"si", "sì", "ok", "ok.", "va bene", "procedi", "confermo", "prima sì", "prima si"}:
        return True
    patterns = ("procedi", "vai pure", "ok timbra", "ok, timbra", "puoi farlo", "fallo", "esegui", "sì procedi", "si procedi")
    return any(p in lower for p in patterns)


def _reasoning_looks_italian(reasoning: str) -> bool:
    """True se il reasoning sembra in italiano (evita di mostrare testo in inglese)."""
    if not reasoning or not reasoning.strip():
        return False
    lower = reasoning.strip().lower()
    # Pattern tipici di output in inglese dall'LLM
    if lower.startswith("the user ") or " the user " in lower:
        return False
    if " wants to " in lower or " want to " in lower:
        return False
    if " from february " in lower or " to request " in lower or " due to " in lower:
        return False
    if " request leave " in lower or " going to the " in lower or " starting " in lower:
        return False
    return True


def _match_direct_action(message: str, actions: list[dict]) -> dict | None:
    """
    Match veloce senza LLM: se il messaggio dell'utente è una azione "precisa"
    (poche parole) che coincide chiaramente con il label/id di un'azione di pagina,
    scatenala subito senza passare dal modello.
    Esempi: "timbra entrata", "timbra uscita", "ferie/rol", "richiedi ferie".
    """
    raw = (message or "").strip()
    if not raw:
        return None
    lower = re.sub(r"\s+", " ", raw.lower())
    # Rimuove caratteri non alfanumerici (es. "ù", punteggiatura) per tollerare piccoli errori di dettatura.
    norm = re.sub(r"[^a-z0-9\s]", "", lower)
    # Se il messaggio è troppo lungo/prolisso, lasciamo decidere all'LLM.
    if len(norm.split()) > 4:
        return None

    best: dict | None = None
    best_score = 0.0

    for a in actions or []:
        label = (a.get("label") or a.get("id") or "").strip()
        if not label:
            continue
        label_lower = re.sub(r"\s+", " ", label.lower())
        aid_lower = (a.get("id") or "").strip().lower()
        label_norm = re.sub(r"[^a-z0-9\s]", "", label_lower)
        aid_norm = re.sub(r"[^a-z0-9\s]", "", aid_lower)

        # Match esatto su label o id → sicuro.
        if norm == label_norm or norm == aid_norm:
            return a

        # Match molto alto su overlap: es. "timbra entrata" vs "Timbra Entrata".
        score = _message_label_overlap_score(raw, label)
        if score > best_score:
            best = a
            best_score = score

    # Soglia alta per evitare falsi positivi: usiamo quick-match solo per casi davvero chiari.
    if best and best_score >= 0.9:
        return best
    return None


def _is_cancel(message: str) -> bool:
    """
    Rileva annullamenti espliciti.
    """
    lower = message.strip().lower()
    if lower in {"no", "no grazie", "annulla"}:
        return True
    patterns = ("non farlo", "lascia stare", "annulla tutto", "annulla la timbratura")
    return any(p in lower for p in patterns)


@app.get("/health")
def health():
    instr = load_instructions(settings)
    repo_code = load_repo_code(settings)
    db_configured = bool(settings.db_dsn)
    llm_configured = bool(settings.llm_api_key) or bool(settings.llm_base_url)

    db_ok = False
    if db_configured:
        try:
            db = DB(settings.db_dsn)
            db_ok = db.ping()
        except Exception as e:
            logger.debug("DB ping failed: %s", e)

    llm_ok = _check_llm_reachable(settings) if llm_configured else False

    return {
        "ok": True,
        "service": settings.name,
        "has_project_md": bool(instr["project_md"].strip()),
        "has_policy_md": bool(instr["policy_md"].strip()),
        "repo_mounted": bool(settings.repo_path),
        "repo_code_loaded": bool(repo_code.strip()),
        "repo_code_length": len(repo_code),
        "db_configured": db_configured,
        "db_ok": db_ok,
        "llm_configured": llm_configured,
        "llm_ok": llm_ok,
        "llm_model": settings.llm_model,
    }


@app.get("/db/ping")
def db_ping():
    if not settings.db_dsn:
        raise HTTPException(status_code=500, detail="DEVIA_DB_DSN non configurato")
    db = DB(settings.db_dsn)
    return {"ok": db.ping()}


@app.get("/repo/check")
def repo_check():
    """
    Check connessione DB + elenco file Models caricati dal repo intranet.
    Utile per verificare che DevIA veda modelli e DB prima di usare la chat.
    """
    repo_files = list_repo_files(settings)
    repo_code = load_repo_code(settings)
    db_ok = None
    if settings.db_dsn:
        try:
            db = DB(settings.db_dsn)
            db_ok = db.ping()
        except Exception as e:
            logger.debug("DB ping failed: %s", e)
            db_ok = False
    return {
        "ok": True,
        "repo_files_count": len(repo_files),
        "repo_files": repo_files[:50],
        "repo_code_length": len(repo_code),
        "db_configured": bool(settings.db_dsn),
        "db_ok": db_ok,
    }


@app.post("/tts")
def tts_endpoint(payload: TtsIn):
    """
    Endpoint TTS semplice: dato un testo, restituisce l'audio generato da Piper.
    Usato dal client per sintetizzare anche i prompt guidati (es. compilazione form).
    """
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Testo vuoto.")
    audio = synthesize_reply(settings, text)
    if not audio:
        # TTS disabilitato o errore: non interrompere il flusso lato client.
        return {"ok": False}
    return {"ok": True, "audio": audio}


@app.post("/debug/context")
def debug_context(payload: ChatIn):
    """
    Stesso body di POST /chat, ma non chiama l'LLM.
    Restituisce user, message, anteprima system prompt e schema DB
    per verificare che il contesto sia corretto (e capire se il blocco è dell'LLM).
    """
    instr = load_instructions(settings)
    repo_code = load_repo_code(settings)
    db_schema = None
    table_names = []
    if settings.db_dsn:
        try:
            db = DB(settings.db_dsn)
            db_schema = db.get_schema()
            table_names = db.get_table_names()
        except Exception as e:
            logger.warning("Schema DB non disponibile: %s", e)

    from .manifest import build_project_manifest
    from .llm import build_system_prompt

    project_manifest = build_project_manifest(
        db_schema=db_schema,
        project_md=instr["project_md"],
        table_names=table_names,
        operations_md=instr.get("operations_md") or "",
    )
    system_prompt = build_system_prompt(
        instr["project_md"],
        instr["policy_md"],
        payload.user,
        app_url=payload.app_url,
        db_schema=db_schema,
        repo_code=repo_code,
        project_manifest=project_manifest,
    )
    return {
        "user_received": payload.user,
        "message": payload.message,
        "db_schema_loaded": db_schema is not None,
        "db_schema_length": len(db_schema) if db_schema else 0,
        "db_schema_preview": (db_schema[:800] + "...") if db_schema and len(db_schema) > 800 else (db_schema or ""),
        "system_prompt_length": len(system_prompt),
        "system_prompt_preview": system_prompt[:2500],
        "llm_model": settings.llm_model,
    }


@app.post("/debug/intent")
def debug_intent(payload: ChatIn):
    """
    Mostra il prompt usato per la classificazione degli intenti e il risultato grezzo del modello.
    Utile per capire cosa vede davvero l'LLM locale quando deve decidere se timbrare/ferie/ROL.
    """
    msg = payload.message.strip()
    conv_id = payload.conversation_id or ""
    has_pending = bool(conv_id and conv_id in PENDING_ACTIONS)
    system, user_prompt = build_intent_prompt(msg, has_pending=has_pending)
    raw = _call_llm(settings, system, user_prompt)
    parsed = classify_intent(settings, msg, has_pending=has_pending)
    return {
        "input_message": msg,
        "system_prompt": system,
        "user_prompt": user_prompt,
        "raw_llm_response": raw,
        "parsed_intent": parsed,
        "llm_model": settings.llm_model,
    }


@app.post("/chat")
def chat(payload: ChatIn):
    instr = load_instructions(settings)
    msg = payload.message.strip()

    logger.info(
        "chat request user_id=%s message_preview=%s",
        payload.user.get("id", "?"),
        msg[:80] + ("..." if len(msg) > 80 else ""),
    )

    if not msg:
        raise HTTPException(status_code=422, detail="Messaggio vuoto")

    # Fallback conv_id per utente se il frontend non invia conversation_id (così il flusso azioni funziona comunque).
    uid_for_conv = str(payload.user.get("id") or payload.user.get("user_id") or "anon")
    conv_id = (payload.conversation_id or "").strip() or f"devia-{uid_for_conv}"
    pending = PENDING_ACTIONS.get(conv_id) if conv_id else None

    # Se c'è un'azione pendente e il messaggio è chiaramente una conferma breve ("sì", "ok", "prima sì", ecc.),
    # trattiamo come conferma senza dipendere dall'LLM (evita che modelli restituiscano correggi_timbratura per "Sì").
    if pending and _is_confirmation(msg):
        intent_data = {"intent": "conferma_pendente", "params": {}}
        intent = "conferma_pendente"
        params = {}
    elif pending and _is_cancel(msg):
        intent_data = {"intent": "annulla_pendente", "params": {}}
        intent = "annulla_pendente"
        params = {}
    else:
        # Flusso intelligente guidato dalla pagina: azioni + form (niente intent fissi)
        actions_count = len(payload.available_actions or [])
        form_fields = payload.form_fields or []
        logger.info(
            "chat received available_actions=%s form_fields=%s (page-driven)",
            actions_count,
            len(form_fields),
        )

        # 0) MATCH DIRETTO SENZA LLM: se il messaggio è una azione precisa (pochi token)
        # e corrisponde chiaramente al label/id di un'azione di pagina, scatenala subito.
        if payload.available_actions and actions_count > 0:
            quick = _match_direct_action(msg, payload.available_actions)
            if quick:
                label = (quick.get("label") or quick.get("id") or "").replace("_", " ")
                active = quick.get("active", True)
                actions_list = payload.available_actions or []
                try:
                    action_index = actions_list.index(quick) if quick in actions_list else None
                except ValueError:
                    action_index = None
                if action_index is None:
                    for idx, a in enumerate(actions_list):
                        if (a.get("id") or "").strip() == (quick.get("id") or "").strip():
                            action_index = idx
                            break
                logger.info(
                    "direct-action match WITHOUT LLM: msg=%r → id=%s label=%r active=%s index=%s",
                    msg,
                    (quick.get("id") or ""),
                    label,
                    active,
                    action_index,
                )
                if not active:
                    return _build_message_response(f"Funzione \"{label}\" non attiva.")
                return _build_message_response(
                    f"Avvio {label}.",
                    client_action="trigger",
                    action_id=quick.get("id") or None,
                    action_index=action_index,
                    action_sequence=None,
                    action_indices=None,
                    form_fill=None,
                    reasoning=None,
                    # Azione terminale (es. timbratura, invia richiesta): NON riapplicare il comando
                    # dopo il refresh della pagina, per evitare doppi click.
                    auto_reapply=False,
                )

        if payload.available_actions and actions_count > 0:
            logger.info(
                "page-driven: calling plan for msg=%r actions=%d form_fields=%d",
                msg[:80] + ("..." if len(msg) > 80 else ""),
                actions_count,
                len(form_fields),
            )
            plan = page_driven_plan(
                settings,
                msg,
                payload.available_actions,
                form_fields if form_fields else None,
            )
            action_ids = plan.get("action_ids") or []
            form_values = plan.get("form_values") or {}
            missing_required = plan.get("missing_required") or []
            reasoning = (plan.get("reasoning") or "").strip()
            has_form = bool(form_fields)
            safe_reasoning = (reasoning if (reasoning and _reasoning_looks_italian(reasoning)) else None)

            logger.info(
                "page-driven plan result: actions=%s missing_required=%s form_keys=%s reasoning_preview=%s",
                action_ids,
                missing_required,
                list(form_values.keys())[:10],
                reasoning[:120],
            )

            actions_list = payload.available_actions or []

            # Azioni candidate da lanciare (in cascata) e/o form da compilare
            first_action_id = action_ids[0] if action_ids else None
            matched = next(
                (a for a in actions_list if (a.get("id") or "").strip() == first_action_id),
                None,
            ) if first_action_id else None

            # Fallback 1: id troncato dall'LLM → match per contenuto (id in id pagina o viceversa)
            if first_action_id and not matched:
                fid = (first_action_id or "").strip()
                candidates = [
                    a for a in actions_list
                    if (a.get("id") or "").strip()
                    and (fid in (a.get("id") or "").strip() or (a.get("id") or "").strip() in fid)
                ]
                if len(candidates) == 1:
                    matched = candidates[0]
                    first_action_id = (matched.get("id") or "").strip()

            # Fallback 2: LLM ha restituito id sbagliato/vuoto → usa pre+fuzzy come prima (match perfetto)
            if not matched and actions_list:
                fallback_id = _generic_fallback_action(msg, actions_list)
                if fallback_id:
                    first_action_id = fallback_id
                    matched = next(
                        (a for a in actions_list if (a.get("id") or "").strip() == fallback_id),
                        None,
                    )

            # Preferenza overlap: se l'LLM ha scelto un'azione ma il fallback ne indica un'altra con score
            # maggiore (es. utente dice "ferie" → preferisci Ferie/ROL, non Timbratura Smart)
            if matched and actions_list:
                fallback_id = _generic_fallback_action(msg, actions_list)
                if fallback_id and (fallback_id or "").strip() != (first_action_id or "").strip():
                    fallback_action = next(
                        (a for a in actions_list if (a.get("id") or "").strip() == (fallback_id or "").strip()),
                        None,
                    )
                    if fallback_action:
                        score_matched = _message_label_overlap_score(msg, matched.get("label") or "")
                        score_fallback = _message_label_overlap_score(msg, fallback_action.get("label") or "")
                        if score_fallback > score_matched:
                            first_action_id = fallback_id
                            matched = fallback_action

            # Calcola lo score dell'azione migliore rispetto al messaggio dell'utente.
            best_score = 0.0
            best_label = ""
            if matched:
                best_label = (matched.get("label") or matched.get("id") or "").strip()
                best_score = _message_label_overlap_score(msg, best_label)

            # Determina il caso: solo navigazione, navigazione con form presente, solo form.
            NAV_THRESHOLD = 0.5
            mode = "FORM_ONLY"
            if not has_form:
                # Nessun form sulla pagina: se c'è un'azione valida, nav pura.
                if first_action_id and matched:
                    mode = "NAV_ONLY"
            else:
                if first_action_id and matched and best_score >= NAV_THRESHOLD:
                    mode = "NAV_WITH_FORM"
                else:
                    mode = "FORM_ONLY"

            logger.info(
                "page-driven mode=%s has_form=%s first_action_id=%s best_label=%r best_score=%.3f",
                mode,
                has_form,
                first_action_id,
                best_label,
                best_score,
            )

            # 1) Modalità di navigazione: lanciamo una o più azioni e chiediamo al client di riapplicare il comando
            # finché il modello continua a scegliere azioni rilevanti (NAV_ONLY / NAV_WITH_FORM).
            if mode in {"NAV_ONLY", "NAV_WITH_FORM"} and first_action_id and matched:
                active = matched.get("active", True)
                label = (matched.get("label") or first_action_id).replace("_", " ")
                try:
                    action_index = actions_list.index(matched) if matched in actions_list else None
                except ValueError:
                    action_index = None
                if action_index is None:
                    for idx, a in enumerate(actions_list):
                        if (a.get("id") or "").strip() == (matched.get("id") or "").strip():
                            action_index = idx
                            break
                if not active:
                    return _build_message_response(f"Funzione \"{label}\" non attiva.")

                action_indices = None
                if len(action_ids) > 1:
                    action_indices = []
                    for aid in action_ids:
                        for ix, a in enumerate(actions_list):
                            if (a.get("id") or "").strip() == (aid or "").strip():
                                action_indices.append(ix)
                                break

                reply_msg = f"Avvio {label}."

                return _build_message_response(
                    reply_msg,
                    client_action="trigger",
                    action_id=first_action_id,
                    action_index=action_index,
                    action_sequence=action_ids if len(action_ids) > 1 else None,
                    action_indices=action_indices,
                    form_fill=None,  # non compiliamo ancora finché stiamo navigando
                    reasoning=safe_reasoning,
                    auto_reapply=True,
                )

            # 2) Modalità solo form: non ci sono più azioni rilevanti da lanciare, usiamo i valori per compilare.
            if form_values and has_form:
                # Se mancano campi obbligatori, chiedili esplicitamente dopo aver provato a compilare ciò che sappiamo.
                extra = ""
                if missing_required:
                    labels_str = ", ".join(missing_required)
                    extra = f" Per procedere mi serve anche: {labels_str}."
                reply_msg = "Compilo i campi con i dati che mi hai indicato." + extra
                return _build_message_response(
                    reply_msg,
                    form_fill=form_values,
                    reasoning=safe_reasoning,
                    auto_reapply=False,
                )

            # 3) Nessuna azione e nessun form compilabile: messaggio generico.
            not_found = "Non ho trovato un'azione o un form corrispondente alla tua richiesta. Prova a essere più specifico."
            return _build_message_response(not_found, reasoning=safe_reasoning, auto_reapply=False)

        intent_data = classify_intent(settings, msg, has_pending=bool(pending))
        intent = str(intent_data.get("intent") or "").strip()
        params = intent_data.get("params") or {}

        # If user was asked "Per quale data?" for ferie/ROL and replied with a date (intent might be "none"), extract params and merge into pending.
        if intent == "none" and pending and conv_id:
            saved_intent = pending.get("intent")
            saved_params = pending.get("params") or {}
            if saved_intent in {"prenota_ferie", "prenota_rol"} and not saved_params.get("start_date"):
                extracted = extract_leave_params(settings, msg)
                if extracted.get("start_date"):
                    merged = dict(saved_params)
                    merged["start_date"] = extracted["start_date"]
                    merged["end_date"] = (extracted.get("end_date") or "").strip() or extracted["start_date"]
                    if extracted.get("note"):
                        merged["note"] = extracted["note"]
                    PENDING_ACTIONS[conv_id] = {
                        "intent": saved_intent,
                        "params": merged,
                        "original_message": pending.get("original_message") or msg,
                    }
                    start_date = merged["start_date"]
                    end_date = merged.get("end_date") or start_date
                    note = merged.get("note", "")
                    summary = f"dal {start_date} al {end_date}"
                    if note:
                        summary += f", motivazione: «{note}»"
                    intent_label = "inserire una richiesta di FERIE" if saved_intent == "prenota_ferie" else "inserire una richiesta di ROL/permesso"
                    return _build_message_response(f"Ho capito: {intent_label} {summary}. Vuoi che proceda?")

        if pending and intent not in {"conferma_pendente", "annulla_pendente"}:
            logger.info(
                "intent con pending: msg=%r parsed_intent=%s (se era 'sì' e vedi correggi_timbratura, l'LLM ha sbagliato; ora usiamo none)",
                msg[:80],
                intent_data,
            )
    # 1a) Gestione conferma / annulla di un'azione pendente.
    if pending and intent in {"conferma_pendente", "annulla_pendente"}:
        if intent == "annulla_pendente":
            PENDING_ACTIONS.pop(conv_id, None)
            return _build_message_response("Ok, non eseguo più l'azione richiesta.")

        action_id = pending.get("action_id")
        saved_intent = pending.get("intent")
        saved_params = pending.get("params") or {}
        original_message = pending.get("original_message") or msg
        PENDING_ACTIONS.pop(conv_id, None)

        # Azione pagina (trigger generico): il frontend clicca l'elemento tramite action_id.
        if action_id is not None:
            return _build_message_response(
                "Procedo con l'azione. Se il bottone in pagina è attivo, lo attivo ora.",
                client_action="trigger",
                action_id=action_id,
            )

        # Timbratura entrata/uscita (legacy): il frontend clicca il bottone della dashboard se attivo.
        if saved_intent in {"timbra_entrata", "timbra_uscita"}:
            return _build_message_response(
                "Procedo con la timbratura. Se il bottone in dashboard è attivo, lo attivo ora.",
                client_action="trigger",
                action_id=saved_intent,
            )

        if saved_intent is None:
            return _build_message_response("Nessuna azione da confermare.")

        action_result = _call_laravel_action(settings, payload.user, saved_intent, saved_params)
        if action_result is not None:
            status = int(action_result.get("status") or 0)
            data = action_result.get("data") or {}
            logger.info(
                "laravel_action result action=%s status=%s user_id=%s data_message=%s",
                saved_intent,
                status,
                payload.user.get("id") or payload.user.get("user_id"),
                data.get("message") or data.get("msg") if isinstance(data, dict) else None,
            )
            # Successo solo con 2xx (200/201). 302 = redirect (es. login per CSRF) = non è successo.
            if status and 200 <= status < 300:
                message = None
                if isinstance(data, dict):
                    message = data.get("message") or data.get("msg")
                    # Se non c'è un messaggio pronto, prova a costruirne uno dai campi noti (tipo/time/timestamp)
                    if not message:
                        time = data.get("time") or data.get("timestamp")
                        if saved_intent in {"timbra_entrata", "timbra_uscita"}:
                            label = "entrata" if saved_intent == "timbra_entrata" else "uscita"
                            if time:
                                message = f"Ho registrato la timbratura di {label} alle {time}."
                            else:
                                message = f"Ho registrato la timbratura di {label}."
                        else:
                            if time:
                                message = f"Azione {saved_intent} completata alle {time}."
                reply = str(message or "Azione completata.")
            else:
                # Errore: 3xx = redirect (es. login per CSRF), 4xx/5xx = errore Laravel.
                if 300 <= status < 400:
                    reply = (
                        "La intranet ha risposto con un reindirizzamento invece che con l'operazione. "
                        "Se il problema persiste, verifica che le route DevIA siano escluse dalla verifica CSRF."
                    )
                else:
                    err_msg = None
                    if isinstance(data, dict):
                        err_msg = data.get("message") or data.get("msg") or data.get("error")
                    if err_msg and isinstance(err_msg, str) and err_msg.strip():
                        reply = err_msg.strip()
                    else:
                        reply = explain_error_to_user(
                            settings=settings,
                            project_md=instr["project_md"],
                            policy_md=instr["policy_md"],
                            user=payload.user,
                            app_url=payload.app_url,
                            user_message=original_message,
                            action_name=saved_intent,
                            action_result=action_result,
                        )
            return _build_message_response(reply)
        # Chiamata Laravel fallita (rete/timeout): messaggio d'errore tramite IA.
        synthetic_result = {"status": 503, "data": {"error": "Impossibile contattare il server dell'intranet (timeout o servizio non raggiungibile)."}}
        reply = explain_error_to_user(
            settings=settings,
            project_md=instr["project_md"],
            policy_md=instr["policy_md"],
            user=payload.user,
            app_url=payload.app_url,
            user_message=original_message,
            action_name=saved_intent,
            action_result=synthetic_result,
        )
        return _build_message_response(reply)

    # 1b) Nuova richiesta di azione: timbra entrata/uscita o ferie/ROL → salva come pendente e chiedi conferma.
    if intent in {"timbra_entrata", "timbra_uscita", "prenota_ferie", "prenota_rol"} and conv_id:
        # Normalize params for ferie/ROL: end_date default to start_date; only keep non-empty values for API
        if intent in {"prenota_ferie", "prenota_rol"}:
            start = (params.get("start_date") or "").strip()
            end = (params.get("end_date") or "").strip()
            note = (params.get("note") or "").strip()
            if start and not end:
                end = start
            params = {}
            if start:
                params["start_date"] = start
            if end:
                params["end_date"] = end
            if note:
                params["note"] = note

        PENDING_ACTIONS[conv_id] = {
            "intent": intent,
            "params": params,
            "original_message": msg,
        }
        intent_label = {
            "timbra_entrata": "timbrare l'ENTRATA",
            "timbra_uscita": "timbrare l'USCITA",
            "prenota_ferie": "inserire una richiesta di FERIE",
            "prenota_rol": "inserire una richiesta di ROL/permesso",
        }.get(intent, intent)

        # If ferie/ROL but missing date, ask for it instead of generic confirmation
        if intent in {"prenota_ferie", "prenota_rol"} and not params.get("start_date"):
            ask = (
                "Ho capito che vuoi richiedere le ferie." if intent == "prenota_ferie" else
                "Ho capito che vuoi richiedere un permesso ROL."
            )
            ask += " Per quale data? (es. il 12 febbraio, dal 10 al 15 marzo)"
            return _build_message_response(ask)

        # Rich confirmation with extracted params when we have them
        if intent in {"prenota_ferie", "prenota_rol"} and params.get("start_date"):
            start_date = params.get("start_date", "")
            end_date = params.get("end_date", "") or start_date
            note = params.get("note", "")
            summary = f"dal {start_date} al {end_date}"
            if note:
                summary += f", motivazione: «{note}»"
            ask = f"Ho capito: {intent_label} {summary}. Vuoi che proceda?"
            return _build_message_response(ask)

        ask = f"Ho capito che vuoi {intent_label}. Vuoi che proceda con questa operazione sulla intranet?"
        return _build_message_response(ask)

    # Nessuna chat generica: se l'intent non è un'azione e non servono dati dal DB, risposta breve in-scope.
    if intent == "none" and not pending and not need_db_data(msg):
        return _build_message_response(
            f"Sono {settings.name}, l'assistente dell'intranet. Puoi chiedermi di timbrare entrata o uscita, "
            "richiedere ferie o ROL, oppure informazioni sui tuoi dati. Cosa vuoi fare?"
        )

    repo_code = load_repo_code(settings)

    # Schema DB per contesto LLM (genera query in base a sorgente/istruzioni)
    db_schema = None
    table_names: list[str] = []
    if settings.db_dsn:
        try:
            db = DB(settings.db_dsn)
            db_schema = db.get_schema()
            table_names = db.get_table_names()
            logger.debug("db_schema loaded, length=%s", len(db_schema) if db_schema else 0)
        except Exception as e:
            logger.warning("Schema DB non disponibile: %s", e)

    from .manifest import build_project_manifest
    project_manifest = build_project_manifest(
        db_schema=db_schema,
        project_md=instr["project_md"],
        table_names=table_names,
        operations_md=instr.get("operations_md") or "",
    )

    uid = str(payload.user.get("id") or payload.user.get("user_id") or "")

    # Pipeline a step: 1) capisco domanda 2) posso rispondere direttamente? 3) serve query? 4) costruisco query 5) eseguo 6) elaboro risposta
    reply: str
    if settings.db_dsn and db_schema and need_db_data(msg):
        # Step 3-4: serve una query → genero SOLO la SQL con prompt dedicato (analisi schema/modelli)
        sql = generate_sql_for_question(
            settings, msg, uid, db_schema, project_manifest
        )
        if sql:
            # Sostituisci eventuale placeholder current_user_id con l'ID reale
            if uid and "current_user_id" in sql and re.match(r"^[a-zA-Z0-9_\-]+$", uid):
                sql = sql.replace("current_user_id", uid)
                logger.debug("Replaced current_user_id with uid=%s in SQL", uid)
            # Step 5: lancio la query
            logger.info("executing SQL (pipeline): %s", sql[:200] + ("..." if len(sql) > 200 else ""))
            try:
                db = DB(settings.db_dsn)
                rows = db.execute_read_only(sql)
                logger.info("SQL returned %s rows", len(rows))
                # Step 6: elaboro i dati per generare la risposta
                reply = answer_from_query_result(
                    settings,
                    instr["project_md"],
                    instr["policy_md"],
                    payload.user,
                    payload.app_url,
                    msg,
                    rows,
                    repo_code=repo_code or "",
                )
            except Exception as e:
                logger.warning("Query non eseguita: %s", e)
                err_result = {"status": 500, "data": {"error": str(e)}}
                reply = explain_error_to_user(
                    settings, instr["project_md"], instr["policy_md"],
                    payload.user, payload.app_url, msg, "consulta_dati", err_result,
                )
        else:
            # Nessuna chat generica: se il generatore non ha prodotto SQL, risposta breve in-scope.
            reply = (
                "Non ho capito quali dati ti servono. Puoi chiedere ad esempio: chi sono, le mie ferie, le mie presenze."
            )
    else:
        # Nessuna chat generica: solo azioni o dati. Se non servono dati dal DB, risposta breve in-scope.
        reply = (
            f"Sono {settings.name}, l'assistente dell'intranet. Puoi chiedermi di timbrare entrata o uscita, "
            "richiedere ferie o ROL, oppure informazioni sui tuoi dati. Cosa vuoi fare?"
        )

    return _build_message_response(reply)
