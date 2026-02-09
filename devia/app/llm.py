"""
Chiamata all'IA (OpenAI-compatible) con contesto: istruzioni, schema DB, utente.
L'LLM può generare una query SQL; la eseguiamo in read-only e usiamo il risultato per la risposta.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx
from openai import OpenAI

from .config import Settings


def build_system_prompt(
    project_md: str,
    policy_md: str,
    user: dict,
    app_url: str | None = None,
    db_schema: str | None = None,
    repo_code: str | None = None,
    project_manifest: str | None = None,
    assistant_name: str = "Kira",
) -> str:
    uid = user.get("id") or user.get("user_id") or ""
    name = assistant_name or "Kira"
    parts = [
        f"You are {name}, the company intranet assistant. You MUST always reply in Italian.",
        "Your scope is STRICTLY LIMITED to: the intranet where you are installed, its database, its APIs/tools, and the project code and documentation provided in this prompt.",
        "You MUST NOT answer generic questions about the outside world (music, history, geography, etc.). If the question is outside the intranet/project scope, clearly say that you cannot answer because you are limited to the intranet and its tools.",
        "CRITICAL: You HAVE read-only access to the intranet database. The schema is provided below. You can run SELECT queries; we execute them and give you the result. NEVER say you don't have access to the database.",
        f"Your name is {name}. When speaking about yourself, use first person (e.g. «Io sono {name}, assistente dell'intranet...», «Ti aiuto con...»).",
        f"CRITICAL: NEVER use the name 'DevIA' in your reply. Your name is ONLY '{name}'. NEVER mention 'correggi timbratura' or 'correzione timbratura' to the user (that feature does not exist).",
        "DOMAIN: This is an EMPLOYEE MANAGEMENT system. Topics: clock-in/clock-out (presenze, timbrature), leave (ferie), permissions/ROL, sickness (malattia), reimbursements (rimborsi), business trips (trasferte). The word 'timbratura' (Italian) means a CLOCK-IN or CLOCK-OUT RECORD (punch), NOT a typo, NOT music/timbre. You can ONLY help record new clock-in/clock-out (timbra entrata, timbra uscita), request leave (ferie), request ROL. You do NOT support 'correggi timbratura' or 'correzione timbratura' (correcting/editing existing clock records). NEVER suggest or mention that the user can ask to correct a timbratura.",
        "",
    ]
    if project_manifest and project_manifest.strip():
        parts.append(project_manifest.strip())
        parts.append("")
    parts.extend([
        "--- WHEN THE USER ASKS WHO YOU ARE (the assistant) ---",
        f'If they ask "chi sei?", "chi sei", "who are you?", "come ti chiami?", "presentati", answer that you are {name}, the intranet assistant. Reply in Italian, first person, for example: "Io sono {name}, l\'assistente dell\'intranet aziendale. Ti aiuto con procedure, ferie, presenze e uso dell\'intranet. Come posso aiutarti?"',
        f"NEVER say you are a generic AI with no name, or that they can call you whatever they want. You have a fixed name: {name}.",
        "--- End ---",
        "",
        "--- CURRENT USER (only ID is passed) ---",
        f"Current user ID (session): {uid}",
        "All other user data (name, email, department, company, etc.) must be obtained by building SELECT queries. Use the database schema below for table/column names (e.g. table 'users' for utenti). **We execute your SELECT for you** and give you the result to answer. Do NOT tell the user to run the query themselves. Do NOT say you don't have access.",
        "--- End ---",
        "",
        "--- WHEN THE USER ASKS «WHO AM I» OR «MY DATA» (chi sono, i miei dati, chi sono io, ecc.) ---",
        "Output ONLY a single SELECT query in a ```sql ... ``` block. Use the **exact** Current user ID value from above (e.g. if it says '42', write WHERE id = 42 or WHERE id = '42' for strings). Do NOT write the literal word 'current_user_id' in the query—we cannot substitute it; use the real ID value. Use the table name from the schema (often 'users' for utenti). We run the query and give you the result; then you answer in natural language. Do NOT tell the user to run the query or to replace anything.",
        "--- End ---",
        "",
        "--- WHEN THE USER ASKS IF YOU SEE / HAVE ACCESS TO THE DATABASE ---",
        "If they ask «vedi il database?», «hai accesso al database?», «vedi il db?», «puoi interrogare il database?», etc., answer YES in Italian: you have read-only access to the intranet database; you receive the table schema in this prompt and you can run SELECT queries (we execute them and give you the result). Example: «Sì, ho accesso in lettura al database dell'intranet: vedo lo schema delle tabelle e posso eseguire query SELECT per rispondere alle tue domande sui dati. Dimmi cosa ti serve.» NEVER say you don't have access to the database or that you're just a generic SQL helper.",
        "--- End ---",
        "",
        "## Project instructions (use for questions about features, procedures, code, intranet)",
        project_md.strip() or "(nessuna)",
        "",
        "## Policy",
        policy_md.strip() or "(nessuna)",
    ])
    if repo_code and repo_code.strip():
        parts.extend([
            "",
            "## Intranet code (use to build queries: tables, columns, relations)",
            "Analyze this code to know how to build SELECT queries for user and other data:",
            "",
            repo_code.strip(),
            "",
        ])
    if app_url:
        base = app_url.rstrip("/")
        parts.extend([
            "",
            "## Intranet base URL (IMPORTANT)",
            f"The user is using the intranet at: {base}",
            "In all replies, for links and APIs use ONLY this base URL.",
            "Never use intranet.devitalia.it or other domains: always use the URL above (e.g. localhost when in development).",
        ])
    if db_schema:
        parts.extend([
            "",
            "## Database schema (read-only)",
            "You have read-only access to the intranet database. Table schema:",
            "",
            db_schema,
            "",
            "**Rule for DB data:** If you need database data to answer, at the end of your reply include exactly one block with a single SELECT query in this format:",
            "```sql",
            "SELECT ... FROM ... WHERE ...",
            "```",
            "Only SELECT, no INSERT/UPDATE/DELETE. We will run the query and give you the result to form the final answer. If you can answer without querying the DB, reply directly without a sql block.",
        ])
    parts.extend([
        "",
        "--- USE OF SQL (vincolo forte) ---",
        "If the question is about **data** (user, presenze, ferie, numbers, lists from the intranet), you **MUST** include in your message a ```sql block with a single SELECT query**; we execute it and give you the result to answer. **Never answer in the abstract** when data are needed. Without a SQL block we cannot fetch data for you.",
        "--- End ---",
        "",
        "--- FINAL RULES ---",
        "Always use the context above to answer. For questions about code, database, procedures or intranet features use the project instructions and DB schema; never say you don't have access to code or database: they were provided. For links/APIs always use the base URL above. Reply in Italian.",
        "**Never** say you cannot execute queries, cannot interact with the database, or that you are 'just an AI' that cannot do things. We execute your SQL and give you the result; you only need to output the ```sql block.",
        "",
        f"REMINDER: You are {name}. We run your SELECT and give you the result. For data questions you MUST output a SQL block with the real user ID. Never say you don't have access or that you can't do it. Reply in Italian.",
    ])
    return "\n".join(parts)


# Frasi che chiedono chi è l'assistente (non l'utente). Se presenti, prependiamo un promemoria
# nel messaggio utente perché alcuni modelli (es. Mistral) ignorano il system prompt.
_IDENTITY_QUERY_PATTERNS = (
    "chi sei",
    "chi sei?",
    "who are you",
    "come ti chiami",
    "presentati",
    "cosa sei",
    "what are you",
)

_IDENTITY_REMINDER = (
    "[Istruzione obbligatoria: rispondi SOLO come Kira. Tu SEI Kira, l'assistente dell'intranet aziendale. "
    "Rispondi in italiano in prima persona (es. Io sono Kira...). Non dire mai 'DevIA'. Non menzionare mai 'correggi timbratura' o 'correzione timbratura'. Non dire mai di essere Mistral, OpenAI o un assistente generico.]\n\n"
)

# Frasi che chiedono i dati dell'utente (chi sono io / con quale utente sono loggato).
# Frasi che chiedono se l'assistente vede/ha accesso al database.
_DB_ACCESS_QUERY_PATTERNS = (
    "vedi il database",
    "vedi il db",
    "hai accesso al database",
    "hai accesso al db",
    "puoi interrogare il database",
    "puoi vedere il database",
    "vedi i dati",
    "accedi al database",
)

_DB_ACCESS_REMINDER = (
    "[L'utente chiede se hai accesso al database. Rispondi SÌ in italiano: hai accesso in lettura, vedi lo schema e puoi eseguire SELECT. Non dire di non avere accesso o di essere un assistente SQL generico.]\n\n"
)

# Risposta fissa quando l'utente chiede solo se vedi/hai accesso al DB (nessuna chiamata LLM).
_DB_ACCESS_FIXED_ANSWER = (
    "Sì, ho accesso in lettura al database dell'intranet: vedo lo schema delle tabelle e posso eseguire query SELECT per rispondere alle tue domande sui dati. Dimmi cosa ti serve."
)

_USER_DATA_QUERY_PATTERNS = (
    "chi sono",
    "chi sono io",
    "con quale utente",
    "quale utente",
    "sono loggato",
    "quale account",
    "i miei dati",
    "dati su di me",
    "presentami",
    "leggendolo dal database",
    "dal database",
)

# Follow-up: utente chiede di farlo noi ("puoi farlo tu", "hai tutto il necessario")
_USER_DO_IT_PATTERNS = (
    "puoi farlo direttamente",
    "puoi farlo tu",
    "fallo tu",
    "fai tu",
    "hai tutto il necessario",
    "hai tutto per farlo",
    "puoi farlo te",
)

_USER_DATA_REMINDER = (
    "[L'utente chiede chi è / i suoi dati. Devi inserire SOLO un blocco ```sql con una SELECT: "
    "usa l'ID utente REALE dal prompt (es. WHERE id = 42), non scrivere 'current_user_id'. "
    "Noi eseguiamo la query e ti diamo il risultato. Non dire all'utente di eseguire la query.]\n\n"
)

_USER_DO_IT_REMINDER = (
    "[L'utente chiede di farlo tu. Sì: noi eseguiamo la tua query. Inserisci un blocco ```sql con una SELECT "
    "usando l'ID utente reale dal prompt (es. WHERE id = 42). Tabella tipica: users. Non dire che non puoi.]\n\n"
)


def _build_user_message_for_llm(user_message: str, user: dict) -> str:
    """
    Per domande su chi è l'assistente prependi promemoria identità (Kira).
    Per domande sui dati utente (chi sono, con quale utente): solo id è passato; prependi promemoria
    che invita a uscire con una SELECT (schema + codice intranet), che eseguiremo.
    """
    raw = user_message.strip()
    lower = raw.lower()
    for pattern in _IDENTITY_QUERY_PATTERNS:
        if pattern in lower or lower == pattern.rstrip("?"):
            return _IDENTITY_REMINDER + "Utente: " + raw
    for pattern in _DB_ACCESS_QUERY_PATTERNS:
        if pattern in lower:
            return _DB_ACCESS_REMINDER + "Utente: " + raw
    for pattern in _USER_DATA_QUERY_PATTERNS:
        if pattern in lower:
            return _USER_DATA_REMINDER + "Utente: " + raw
    for pattern in _USER_DO_IT_PATTERNS:
        if pattern in lower:
            return _USER_DO_IT_REMINDER + "Utente: " + raw
    return raw


def _call_llm(settings: Settings, system: str, user_message: str) -> str:
    api_key = settings.llm_api_key or "ollama"
    kwargs = {"api_key": api_key}
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url
    client = OpenAI(**kwargs)
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        max_tokens=1024,
        temperature=0.3,
    )
    choice = response.choices[0] if response.choices else None
    if not choice or not choice.message or not choice.message.content:
        return ""
    return choice.message.content.strip()


def _fetch_laravel_manifest(settings: Settings) -> Optional[Dict[str, Any]]:
    """
    Carica il manifest dei tool dall'app Laravel configurata.
    Usa DEVIA_LARAVEL_BASE_URL come base e chiama /manifest.
    """
    base = settings.laravel_base_url
    if not base:
        return None
    url = base.rstrip("/") + "/manifest"
    headers: Dict[str, str] = {}
    if settings.laravel_tool_token:
        headers["Authorization"] = f"Bearer {settings.laravel_tool_token}"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        # In demo non blocchiamo la chat se il manifest non è raggiungibile
        return None


def _tools_from_manifest(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Converte il manifest Laravel nel formato tools OpenAI-compatible.
    """
    tools: List[Dict[str, Any]] = []
    for tool in manifest.get("tools", []):
        name = tool.get("name")
        if not name:
            continue
        params = tool.get("parameters") or {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description", ""),
                    "parameters": params,
                },
            }
        )
    return tools


def _call_laravel_tool(
    settings: Settings,
    manifest: Dict[str, Any],
    tool_name: str,
    args: Dict[str, Any],
    user: dict,
) -> Dict[str, Any]:
    """
    Esegue una singola chiamata tool verso Laravel in base al manifest.
    Aggiunge sempre l'ID utente come X-Devia-User-Id per evitare che l'LLM lo inventi.
    """
    base = settings.laravel_base_url
    if not base:
        return {"ok": False, "error": "DEVIA_LARAVEL_BASE_URL non configurato"}

    tool_def = None
    for t in manifest.get("tools", []):
        if t.get("name") == tool_name:
            tool_def = t
            break
    if not tool_def:
        return {"ok": False, "error": f"Tool '{tool_name}' non definito nel manifest"}

    method = str(tool_def.get("method") or "POST").upper()
    endpoint = tool_def.get("endpoint") or ""
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    url = base.rstrip("/") + endpoint

    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        # Passiamo l'utente corrente in header dedicato
        "X-Devia-User-Id": str(user.get("id") or user.get("user_id") or ""),
    }
    if settings.laravel_tool_token:
        headers["Authorization"] = f"Bearer {settings.laravel_tool_token}"

    try:
        with httpx.Client(timeout=10.0) as client:
            if method == "GET":
                resp = client.get(url, headers=headers, params=args)
            else:
                resp = client.post(url, headers=headers, json=args)
        data: Any
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        return {
            "ok": resp.status_code >= 200 and resp.status_code < 300,
            "status": resp.status_code,
            "data": data,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _call_llm_with_tools(
    settings: Settings,
    system: str,
    user_message: str,
    user: dict,
) -> tuple[str, bool]:
    """
    Chiamata LLM con supporto tools OpenAI-style.
    Ritorna (risposta_testuale, tools_usati_bool).
    """
    manifest = _fetch_laravel_manifest(settings)
    if not manifest:
        # Nessun manifest → nessun tool
        return _call_llm(settings, system, user_message), False

    tools = _tools_from_manifest(manifest)
    if not tools:
        return _call_llm(settings, system, user_message), False

    api_key = settings.llm_api_key or "ollama"
    kwargs: Dict[str, Any] = {"api_key": api_key}
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url
    client = OpenAI(**kwargs)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message},
    ]

    # Prima chiamata: lascia decidere al modello se usare tool
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        max_tokens=1024,
        temperature=0.3,
    )
    choice = response.choices[0] if response.choices else None
    if not choice or not choice.message:
        return "", False

    msg = choice.message
    tool_calls = getattr(msg, "tool_calls", None)
    if not tool_calls:
        # Nessun tool usato: usiamo il contenuto come risposta
        content = (msg.content or "").strip() if msg.content else ""
        return content, False

    # Eseguiamo in sequenza i tool richiesti, poi facciamo una seconda chiamata
    tools_used = False
    messages.append(
        {
            "role": msg.role,
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        }
    )

    for tc in tool_calls:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        result = _call_laravel_tool(settings, manifest, tc.function.name, args, user)
        tools_used = True
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )

    # Seconda chiamata: il modello vede i risultati dei tool e produce la risposta finale
    final = client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        max_tokens=512,
        temperature=0.3,
    )
    final_choice = final.choices[0] if final.choices else None
    if not final_choice or not final_choice.message:
        return "", tools_used
    content = (final_choice.message.content or "").strip() if final_choice.message.content else ""
    return content, tools_used


def extract_sql_from_response(text: str) -> str | None:
    """Estrae la prima query da un blocco ```sql ... ```."""
    m = re.search(r"```sql\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip() or None


def answer_from_query_result(
    settings: Settings,
    project_md: str,
    policy_md: str,
    user: dict,
    app_url: str | None,
    question: str,
    query_result: list[dict],
    repo_code: str | None = None,
) -> str:
    """Seconda chiamata LLM: dato il risultato della query, risponde in linguaggio naturale."""
    system = build_system_prompt(
        project_md, policy_md, user, app_url, db_schema=None, repo_code=repo_code,
        assistant_name=getattr(settings, "name", "Kira"),
    )
    rows_str = str(query_result) if query_result else "Nessun risultato."
    user_message = (
        f"The user asked: «{question}»\n\n"
        f"Result of the query executed on the database:\n{rows_str}\n\n"
        "Reply to the user in natural language in Italian, using only this data. Do not invent data."
    )
    return _call_llm(settings, system, user_message)


def explain_action_result(
    settings: Settings,
    project_md: str,
    policy_md: str,
    user: dict,
    app_url: str | None,
    user_message: str,
    action_name: str,
    action_result: dict,
) -> str:
    """
    Usa il LLM per trasformare il risultato di un tool/azione Laravel
    in una spiegazione chiara per l'utente, restando nel perimetro intranet.
    """
    system = build_system_prompt(
        project_md=project_md,
        policy_md=policy_md,
        user=user,
        app_url=app_url,
        db_schema=None,
        repo_code=None,
        project_manifest=None,
        assistant_name=getattr(settings, "name", "Kira"),
    )
    action_json = json.dumps(action_result, ensure_ascii=False)
    user_text = (
        f"L'utente ha scritto: «{user_message}».\n"
        f"Hai eseguito l'azione '{action_name}' tramite l'API/tool Laravel corrispondente "
        f"e hai ricevuto questo risultato (JSON):\n{action_json}\n\n"
        "Spiega all'utente in italiano cosa è successo (successo o errore), "
        "usando SOLO le informazioni contenute in questo risultato e nel contesto intranet. "
        "Non aggiungere dettagli inventati e non parlare di argomenti generici fuori dall'intranet."
    )
    return _call_llm(settings, system, user_text)


def explain_error_to_user(
    settings: Settings,
    project_md: str,
    policy_md: str,
    user: dict,
    app_url: str | None,
    user_message: str,
    action_name: str,
    action_result: dict,
) -> str:
    """
    Usa il LLM per convertire un errore (messaggio tecnico, SQLSTATE, validazione, ecc.)
    in una risposta chiara e colloquiale per l'utente, senza esporre dettagli tecnici.
    """
    system = (
        "Sei Kira, l'assistente dell'intranet aziendale. Non dire mai 'DevIA'. Rispondi SEMPRE in italiano, in prima persona.\n"
        "L'utente ha chiesto di eseguire un'azione sulla intranet ma l'operazione è fallita.\n"
        "Il tuo compito è trasformare l'errore tecnico che vedi nel JSON qui sotto in una risposta breve, "
        "chiara e utile per l'utente: spiega che non sei riuscita a completare l'azione e, se possibile, "
        "il motivo in parole semplici (es. «non sei nella rete locale», «dati non validi», «problema tecnico»).\n"
        "NON copiare SQLSTATE, stack trace, codici HTTP o messaggi tecnici grezzi. "
        "Concludi con un suggerimento pratico (es. «procedi manualmente dalla intranet» o «contatta l'amministratore»).\n"
        "Risposta in 1-3 frasi, tono colloquiale."
    )
    action_json = json.dumps(action_result, ensure_ascii=False)
    user_text = (
        f"L'utente ha scritto: «{user_message}».\n"
        f"L'azione richiesta era: {action_name}.\n"
        f"Risultato/errore restituito dal sistema (JSON):\n{action_json}\n\n"
        "Rispondi all'utente in italiano, in prima persona, trasformando questo errore in un messaggio chiaro e breve."
    )
    out = _call_llm(settings, system, user_text)
    return (out or "").strip() or "Mi dispiace, non sono riuscita a completare l'operazione. Procedi manualmente dalla intranet o contatta l'amministratore."


def _intent_definitions() -> list[dict]:
    """
    Definizione centralizzata degli intent per la demo.
    """
    return [
        {
            "name": "timbra_entrata",
            "description": "Registra una timbratura di ENTRATA per l'utente che sta parlando.",
            "params": {},
        },
        {
            "name": "timbra_uscita",
            "description": "Registra una timbratura di USCITA per l'utente che sta parlando.",
            "params": {},
        },
        {
            "name": "prenota_ferie",
            "description": "Crea una richiesta di FERIE per l'utente (es. una data singola o un intervallo di date). Extract ALL mentioned info: dates and reason/motivation.",
            "params": {
                "start_date": "data di inizio in YYYY-MM-DD (use 2026 if year not specified)",
                "end_date": "data di fine in YYYY-MM-DD; if single day or only one date mentioned, set equal to start_date",
                "note": "motivazione/ragione se l'utente la indica (es. 'perché vado in montagna', 'per matrimonio')",
            },
        },
        {
            "name": "prenota_rol",
            "description": "Crea una richiesta di ROL/permesso orario per l'utente. Extract ALL mentioned info: dates and reason.",
            "params": {
                "start_date": "data di inizio in YYYY-MM-DD (use 2026 if year not specified)",
                "end_date": "data di fine in YYYY-MM-DD; if single day, set equal to start_date",
                "note": "motivazione/ragione se indicata dall'utente",
            },
        },
    ]


def build_intent_prompt(message: str, has_pending: bool = False) -> tuple[str, str]:
    """
    Costruisce (system_prompt, user_message) per la classificazione degli intenti.
    Utile sia in produzione che in /debug/intent.
    """
    intents = _intent_definitions()

    intents_text_lines = []
    for it in intents:
        name = it["name"]
        desc = it["description"]
        intents_text_lines.append(f'- "{name}": {desc}')
    intents_text = "\n".join(intents_text_lines)

    if has_pending:
        system = (
            "You are an intent classifier for Kira, an assistant in an EMPLOYEE MANAGEMENT system "
            "(clock-in/clock-out, leave, permissions/ROL, sickness, reimbursements, business trips). "
            "There is a PENDING ACTION waiting for user confirmation. Output ONLY valid JSON.\n\n"
            "CRITICAL: If the message ONLY confirms (yes, ok, sì, si, prima sì, procedi, vai, conferma) with no other request → intent \"conferma_pendente\". "
            "Do NOT use correggi_timbratura or any 'correzione timbratura' intent: that feature does not exist. Confirmations must be \"conferma_pendente\".\n"
            "If the message ONLY cancels (no, don't, annulla, lascia stare) with no other request → intent \"annulla_pendente\".\n"
            "If the message is a NEW request (timbrare entrata/uscita, ferie, ROL), choose the matching intent:\n"
            f"{intents_text}\n\n"
            'Output format: { "intent": "...", "params": { ... } }. Only JSON, no other text.\n'
        )
    else:
        system = (
            "You are an intent classifier for Kira. DOMAIN: EMPLOYEE MANAGEMENT system. "
            "Topics: clock-in/clock-out (presenze, timbrature), leave (ferie), permissions/ROL, sickness (malattia), reimbursements (rimborsi), business trips (trasferte).\n\n"
            "CRITICAL: The Italian word 'timbratura' means a CLOCK-IN or CLOCK-OUT RECORD (punch), i.e. an attendance record. "
            "It does NOT mean: typo, spelling, music/timbre, or text correction. Ignore any interpretation as grammar/typo/music.\n\n"
            "Do NOT use or output intent 'correggi_timbratura' or 'correzione timbratura'. That feature does not exist. Use only the intents listed below.\n\n"
            "Understand the user's INTENT from context. Users write informally; interpret the meaning.\n\n"
            "Available intents:\n"
            f"{intents_text}\n\n"
            "Rules:\n"
            "- timbra_entrata: user wants to RECORD clock-in NOW (arrival, entering). Phrases like 'timbra entrata', 'entrata', 'sembra entrato', 'registra entrata'.\n"
            "- timbra_uscita: user wants to RECORD clock-out NOW (leaving).\n"
            "- prenota_ferie: request leave/vacation. ALWAYS try to extract from the message: start_date and end_date in YYYY-MM-DD (current year 2026 if not specified); if user says only one date (e.g. 'il 12 febbraio') set both start_date and end_date to that date; extract 'note' for reason/motivation (e.g. 'perché vado in montagna' -> note: 'vado in montagna').\n"
            "- prenota_rol: request ROL/permission. Same as ferie: extract start_date, end_date (YYYY-MM-DD, year 2026 if missing), and note if present.\n"
            "- none: none of the above.\n\n"
            "CRITICAL: Short confirmations like 'sì', 'si', 'sì procedi', 'prima sì', 'ok', 'vai' when there is a PENDING action must be intent \"conferma_pendente\", NOT a new action.\n"
            'Output ONLY one JSON object: { "intent": "<intent_name>", "params": { ... } }. No other text.\n'
        )
    user_message = (
        f'User message: "{message}".\n\n'
        "Output ONLY one JSON object: { \"intent\": \"...\", \"params\": { ... } }. "
        "For prenota_ferie/prenota_rol: put dates in YYYY-MM-DD (e.g. 2026-02-12 for 'il 12 febbraio'); if only one date is given, set both start_date and end_date to it; put user reason/motivation in 'note' if present. No other text."
    )
    return system, user_message


def extract_leave_params(settings: Settings, message: str) -> Dict[str, Any]:
    """
    When the user is specifying a date/reason for a pending leave request (ferie/ROL),
    extract start_date, end_date, note from the message. Used to merge into pending params.
    Returns dict with keys start_date, end_date, note (values empty string if not found).
    """
    message = (message or "").strip()
    if not message:
        return {}
    system = (
        "You are a parameter extractor for Kira. The user is specifying the DATE or REASON for a leave request (ferie or ROL). "
        "Extract ONLY: start_date (YYYY-MM-DD, use year 2026 if not specified), end_date (YYYY-MM-DD; if single day set equal to start_date), note (motivation/reason if present). "
        "Examples: 'il 12 febbraio' -> start_date 2026-02-12, end_date 2026-02-12; 'dal 10 al 15 marzo' -> start_date 2026-03-10, end_date 2026-03-15; 'perché vado in montagna' -> note 'vado in montagna'. "
        "Output ONLY a JSON object: { \"start_date\": \"...\" or \"\", \"end_date\": \"...\" or \"\", \"note\": \"...\" or \"\" }. No other text."
    )
    user_text = f'User message: "{message}".\n\nOutput only the JSON object.'
    raw = _call_llm(settings, system, user_text)
    if not raw:
        return {}
    m = re.search(r"\{[^{}]*\}", raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return {
            "start_date": (data.get("start_date") or "").strip(),
            "end_date": (data.get("end_date") or "").strip(),
            "note": (data.get("note") or "").strip(),
        }
    except Exception:
        return {}


def build_page_action_match_prompt(message: str, available_actions: List[Dict[str, Any]]) -> tuple[str, str]:
    """
    Costruisce (system_prompt, user_message) per far verificare all'LLM
    se tra gli input/azioni della pagina passati in parametro c'è il comando da eseguire.
    """
    actions_text_lines = []
    for a in available_actions:
        aid = a.get("id") or ""
        label = (a.get("label") or aid).strip()
        active = a.get("active", True)
        actions_text_lines.append(f'- id "{aid}": label "{label}" (active={active})')
    actions_text = "\n".join(actions_text_lines)

    system = (
        "You are Kira's action matcher. The CLIENT passes you the list of INPUT/ACTIONS on the page (buttons, links). "
        "Your task: return the action_id that BEST MATCHES what the user asked for (by label/meaning).\n\n"
        "CRITICAL: Return the action that CORRESPONDS to the user's request, NOT a different action. "
        "Example: if the user says 'timbra entrata', you MUST return the id of the action whose label is 'timbra entrata' / 'TIMBRA ENTRATA' (the entry clock button), "
        "even if that action is inactive (active=false). Do NOT return the id of another action (e.g. 'Timbratura Smart') just because it is active. "
        "We need the exact match to the user's words; we will then tell them 'Funzione non attiva' if that action is inactive.\n\n"
        "Page inputs/actions (use ONLY these ids):\n"
        f"{actions_text}\n\n"
        "Rules: (1) Match by meaning and label: 'timbra entrata' → id of 'timbra entrata' / 'TIMBRA ENTRATA'; 'timbra uscita' → id of uscita; 'apri timbrature' → id of link 'Apri Timbrature'. "
        "(2) If the user is NOT asking to run any of these actions, output action_id null.\n\n"
        "Output ONLY a single JSON object: { \"action_id\": \"<id>\" } with the exact id from the list, or { \"action_id\": null }. No other text."
    )
    user_message = f'User message: "{message}".\n\nWhich action id (from the list) best matches what the user asked? Output only the JSON object.'
    return system, user_message


def page_driven_plan(
    settings: Settings,
    message: str,
    available_actions: List[Dict[str, Any]],
    form_fields: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    Page-driven flow (domain-agnostic: intranet, ecommerce, any site).
    From user message + page actions + optional form fields, the LLM decides:
    (1) which action(s) to trigger (by id, in order), (2) form field values from the message (by label),
    (3) which required fields are still missing, (4) short reasoning.
    Returns: { "action_ids": [...], "form_values": {...}, "missing_required": [...], "reasoning": "..." }.
    """
    message = (message or "").strip()
    if not message:
        return {"action_ids": [], "form_values": {}, "missing_required": [], "reasoning": ""}

    actions_text_lines = []
    for a in available_actions or []:
        aid = a.get("id") or ""
        label = (a.get("label") or aid).strip()
        active = a.get("active", True)
        actions_text_lines.append(f'- id "{aid}": label "{label}" (active={active})')
    actions_text = "\n".join(actions_text_lines) if actions_text_lines else "(none)"

    form_fields = form_fields or []
    form_text_lines = []
    for f in form_fields:
        label = (f.get("label") or "").strip()
        required = f.get("required", False)
        ftype = (f.get("type") or "text").strip()
        if label:
            form_text_lines.append(f'- label "{label}" required={bool(required)} type={ftype}')
    form_text = "\n".join(form_text_lines) if form_text_lines else "(no form on page)"

    system = (
        "You are Kira, a generic page-driven assistant. The site can be anything: intranet, ecommerce, CRM, etc.\n\n"
        "The user says what they want. You have: (1) a list of ACTIONS on the page (buttons/links) with id and label; (2) optionally FORM FIELDS (label, required, type).\n\n"
        "Your task:\n"
        "1) action_ids: array of action ids to trigger IN ORDER. Understand the user's intent and pick the action(s) whose LABEL matches by MEANING. Use ONLY ids from the list. The user may give a long phrase (e.g. 'I want to request leave on 12 Feb because I go to the mountains' or 'add to cart the blue shirt size M'); you MUST still choose the matching action (e.g. the one about 'request leave' / 'Richiedi ferie', or 'Add to cart'). NEVER return empty action_ids when the user clearly refers to one of the listed actions.\n"
        "2) form_values: object mapping each form field LABEL to a value extracted from the message. Use the exact label as key. Extract dates, quantities, descriptions, etc. as appropriate; dates in YYYY-MM-DD.\n"
        "3) missing_required: array of labels of required form fields that have no value in form_values.\n"
        "4) reasoning: one short sentence IN ITALIAN explaining what you understood and what you are doing (e.g. 'Richiesta di ferie: avvio Consulta/Richiedi ferie.').\n\n"
        "CRITICAL: Output reasoning and any user-facing text ONLY in Italian. Never in English.\n\n"
        "Page actions (use ONLY these ids):\n"
        f"{actions_text}\n\n"
        "Form fields on page:\n"
        f"{form_text}\n\n"
        "Output ONLY one JSON: { \"action_ids\": [\"id1\", ...], \"form_values\": { \"Label\": \"value\", ... }, \"missing_required\": [\"Label\", ...], \"reasoning\": \"...\" }. No other text."
    )
    user_text = f'User message: "{message}".\n\nOutput only the JSON object.'
    raw = _call_llm(settings, system, user_text)
    if not raw:
        fallback_id = _generic_fallback_action(message, available_actions or [])
        return {
            "action_ids": [fallback_id] if fallback_id else [],
            "form_values": {},
            "missing_required": list(f.get("label") for f in form_fields if f.get("required")),
            "reasoning": "Uso il match dal testo." if fallback_id else "",
        }

    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        fallback_id = _generic_fallback_action(message, available_actions or [])
        return {
            "action_ids": [fallback_id] if fallback_id else [],
            "form_values": {},
            "missing_required": [],
            "reasoning": "Uso il match dal testo." if fallback_id else "",
        }
    try:
        data = json.loads(m.group(0))
        action_ids = data.get("action_ids")
        if not isinstance(action_ids, list):
            action_ids = [action_ids] if action_ids else []
        action_ids = [str(a).strip() for a in action_ids if a]
        form_values = data.get("form_values") or {}
        if not isinstance(form_values, dict):
            form_values = {}
        missing_required = data.get("missing_required") or []
        if not isinstance(missing_required, list):
            missing_required = []
        missing_required = [str(l).strip() for l in missing_required if l]
        reasoning = (data.get("reasoning") or "").strip()

        # Fallback generico: se l'LLM ha restituito action_ids vuoti, prova match per token/label
        if not action_ids and available_actions:
            fallback_id = _generic_fallback_action(message, available_actions)
            if fallback_id:
                action_ids = [fallback_id]
                if not reasoning:
                    reasoning = "Ho trovato l'azione dalla tua richiesta."

        return {
            "action_ids": action_ids,
            "form_values": form_values,
            "missing_required": missing_required,
            "reasoning": reasoning,
        }
    except Exception:
        fallback_id = _generic_fallback_action(message, available_actions or [])
        return {
            "action_ids": [fallback_id] if fallback_id else [],
            "form_values": {},
            "missing_required": [],
            "reasoning": "Uso il match dal testo." if fallback_id else "",
        }


def _normalize_action_text(text: str) -> str:
    """
    Normalizzazione semplice per il pre-matching:
    - lowercase
    - rimozione caratteri non alfanumerici/spazi
    - collassa spazi multipli
    """
    text = (text or "").lower()
    cleaned_chars: List[str] = []
    for ch in text:
        if ch.isalnum() or ch.isspace():
            cleaned_chars.append(ch)
    cleaned = "".join(cleaned_chars)
    return " ".join(cleaned.split())


def _token_similar(a: str, b: str) -> bool:
    """
    Similarità approssimata tra singoli token:
    - uguali dopo normalizzazione
    - oppure condividono lo stesso "stem" di almeno 4 caratteri (es. timbro/timbra/timbrare).
    """
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    stem_len = 4
    if len(a) >= stem_len and len(b) >= stem_len:
        return a[:stem_len] == b[:stem_len]
    return False


def _pre_match_page_action(message: str, available_actions: List[Dict[str, Any]]) -> Optional[str]:
    """
    Pre-matching deterministico PRIMA di chiamare l'LLM:
    - se il testo utente coincide (dopo normalizzazione) con UNA sola label disponibile,
      ritorna direttamente il relativo action_id.
    - Esempio: 'timbra entrata' → bottone 'TIMBRA ENTRATA'.
    - Per frasi più vaghe (es. solo 'timbra') non fa nulla: decide l'LLM.
    """
    msg_norm = _normalize_action_text(message)
    if not msg_norm:
        return None

    exact_matches: List[str] = []
    for a in available_actions:
        aid = str(a.get("id") or "").strip()
        label = str(a.get("label") or "").strip()
        if not aid or not label:
            continue
        lab_norm = _normalize_action_text(label)
        if not lab_norm:
            continue
        if msg_norm == lab_norm:
            exact_matches.append(aid)

    if len(exact_matches) == 1:
        return exact_matches[0]
    return None


def _fuzzy_match_page_action(message: str, available_actions: List[Dict[str, Any]]) -> Optional[str]:
    """
    Fuzzy match molto semplice quando non c'è un match esatto:
    - confronta per parole (token) tra messaggio e label
    - calcola una score = token_in_comune / token_nel_messaggio
    - se esiste UNA sola azione con score >= 0.6, la consideriamo la migliore candidata.

    Esempi:
    - msg: "richiedi trasferta"
      label: "Richiedi una trasferta per un giorno specifico" → overlap {richiedi, trasferta} = 2/2 → 1.0
    """
    msg_norm = _normalize_action_text(message)
    if not msg_norm:
        return None
    msg_tokens = [t for t in msg_norm.split() if t]
    if not msg_tokens:
        return None

    best_id: Optional[str] = None
    best_score = 0.0

    for a in available_actions:
        aid = str(a.get("id") or "").strip()
        label = str(a.get("label") or "").strip()
        if not aid or not label:
            continue
        lab_norm = _normalize_action_text(label)
        if not lab_norm:
            continue
        lab_tokens = [t for t in lab_norm.split() if t]
        if not lab_tokens:
            continue

        # Score: frazione di token del messaggio presenti nella label
        overlap = 0
        for t in msg_tokens:
            for lt in lab_tokens:
                if _token_similar(t, lt):
                    overlap += 1
                    break
        if overlap == 0:
            continue
        score = overlap / float(len(msg_tokens))

        # Se il messaggio è quasi contenuto nella label o viceversa, alza lo score
        if msg_norm in lab_norm or lab_norm in msg_norm:
            score = max(score, 0.9)

        if score > best_score:
            best_score = score
            best_id = aid

    # Usa solo se il match è sufficientemente forte
    if best_id and best_score >= 0.6:
        return best_id
    return None


def _message_label_overlap_score(message: str, label: str) -> float:
    """Score 0..1: quanto i token del messaggio sono presenti nella label (per preferire azione più pertinente)."""
    msg_norm = _normalize_action_text(message)
    lab_norm = _normalize_action_text(label or "")
    if not msg_norm or not lab_norm:
        return 0.0
    msg_tokens = [t for t in msg_norm.split() if t]
    lab_tokens = set(lab_norm.split())
    if not msg_tokens:
        return 0.0
    overlap = sum(1 for t in msg_tokens if t in lab_tokens)
    return overlap / float(len(msg_tokens))


def _generic_fallback_action(message: str, available_actions: List[Dict[str, Any]]) -> Optional[str]:
    """
    Fallback generico quando l'LLM non restituisce action_ids: pre-match esatto o fuzzy
    per token overlap tra messaggio e label. Domain-agnostic (intranet, ecommerce, ecc.).
    """
    if not message or not available_actions:
        return None
    pre = _pre_match_page_action(message, available_actions)
    if pre:
        return pre
    return _fuzzy_match_page_action(message, available_actions)


def classify_page_action(
    settings: Settings,
    message: str,
    available_actions: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Usa l'LLM per capire quale azione della pagina (se una) l'utente vuole eseguire.
    Ritorna l'action_id se c'è un match, None altrimenti.
    """
    message = message.strip()
    if not message or not available_actions:
        return None

    valid_ids = {str(a.get("id") or "").strip() for a in available_actions if a.get("id")}
    if not valid_ids:
        return None

    # Pre-matching: se il testo utente corrisponde esattamente (dopo normalizzazione)
    # alla label di UNA sola azione, usiamo direttamente quell'action_id senza chiamare l'LLM.
    # Questo copre i casi chiari tipo "timbra entrata" / "Correggi" e lascia all'LLM
    # le frasi più vaghe come "timbra" dove ha senso valutare eventuali alternative (es. Timbratura Smart).
    pre_match = _pre_match_page_action(message, available_actions)
    if pre_match and pre_match in valid_ids:
        return pre_match

    # Fuzzy match: se non c'è un match esatto ma il messaggio è chiaramente riferito
    # a UNA delle label (es. "richiedi trasferta" vs "Richiedi una trasferta per un giorno specifico"),
    # prova ad usare quella senza coinvolgere l'LLM.
    fuzzy_id = _fuzzy_match_page_action(message, available_actions)
    if fuzzy_id and fuzzy_id in valid_ids:
        return fuzzy_id

    system, user_message = build_page_action_match_prompt(message, available_actions)
    raw = _call_llm(settings, system, user_message)
    if not raw:
        return None

    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        aid = data.get("action_id")
        if aid is None:
            return None
        aid = str(aid).strip()
        return aid if aid in valid_ids else None
    except Exception:
        return None


def classify_intent(
    settings: Settings,
    message: str,
    has_pending: bool = False,
) -> Dict[str, Any]:
    """
    Classificatore di intenti basato su LLM, pensato per modelli locali.
    Non usa function-calling, ma chiede al modello di restituire SOLO un JSON
    con { "intent": "...", "params": { ... } }.

    Intent possibili (per la demo intranet):
    - "timbra_entrata"
    - "timbra_uscita"
    - "prenota_ferie"
    - "prenota_rol"
    - "conferma_pendente" / "annulla_pendente" (se has_pending)
    - "none" (quando nessuna azione è appropriata)
    """
    message = message.strip()
    if not message:
        return {"intent": "none", "params": {}}

    system, user_message = build_intent_prompt(message, has_pending=has_pending)
    raw = _call_llm(settings, system, user_message)
    if not raw:
        return {"intent": "none", "params": {}}

    # Estrai il primo oggetto JSON dalla risposta, ignorando eventuali rumori
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {"intent": "none", "params": {}}
    json_str = m.group(0)
    try:
        data = json.loads(json_str)
        intent = str(data.get("intent") or "none").strip()
        params = data.get("params") or {}
        # Normalizza: se l'intent non è tra quelli noti, torna 'none'
        valid_names = {it["name"] for it in _intent_definitions()} | {"none", "conferma_pendente", "annulla_pendente"}
        if intent not in valid_names:
            intent = "none"
        if not isinstance(params, dict):
            params = {}
        return {"intent": intent, "params": params}
    except Exception:
        return {"intent": "none", "params": {}}


def need_db_data(message: str) -> bool:
    """
    Step 1-2: capisco la domanda → posso rispondere direttamente? No se servono dati dal DB.
    True se la domanda richiede dati dal database (utente, presenze, ferie, ecc.).
    """
    lower = message.strip().lower()
    patterns = (
        "chi sono",
        "chi sono io",
        "i miei dati",
        "dati su di me",
        "presentami",
        "con quale utente",
        "quale account",
        "sono loggato",
        "leggendo dal database",
        "dal database",
        "leggendolo dal database",
        "presenze",
        "ferie",
        "permessi",
        "timbrature",
        "i miei",
        "le mie ",
        "dammi i ",
        "quante ",
        "quanti ",
        "elenco ",
        "lista ",
    )
    return any(p in lower for p in patterns)


def build_sql_generator_prompt(
    question: str,
    user_id: str,
    db_schema: str,
    project_manifest: str | None = None,
) -> tuple[str, str]:
    """
    Step 4: prompt dedicato solo alla costruzione della query.
    Restituisce (system_prompt, user_message) per una chiamata che deve produrre SOLO SQL.
    """
    # Per colonna id numerica: WHERE id = 42; per stringa: WHERE id = '42'
    uid_val = user_id if user_id.isdigit() else repr(user_id)
    system = (
        "You are a SQL generator. Your ONLY task is to output a single SELECT query.\n"
        "Rules:\n"
        "- Use ONLY table and column names that appear in the schema below.\n"
        f"- Current user ID (use this exact value in WHERE): {uid_val}. Example: WHERE id = {uid_val}.\n"
        "- Output ONLY a ```sql ... ``` block with one SELECT. No explanation, no other text.\n"
        "- Only SELECT; no INSERT/UPDATE/DELETE.\n"
    )
    if project_manifest and project_manifest.strip():
        system += "\nProject context (tables/domains):\n" + project_manifest.strip() + "\n\n"
    system += "Database schema:\n" + db_schema
    user_msg = f"Question: {question}\n\nOutput only the SQL query in ```sql ... ```."
    return system, user_msg


def generate_sql_for_question(
    settings: Settings,
    question: str,
    user_id: str,
    db_schema: str,
    project_manifest: str | None = None,
) -> str | None:
    """
    Step 4: genera solo la query analizzando schema e domanda.
    Una sola chiamata LLM con prompt focalizzato su "output solo SQL".
    """
    if not db_schema or not question.strip():
        return None
    system, user_msg = build_sql_generator_prompt(question, user_id, db_schema, project_manifest)
    raw = _call_llm(settings, system, user_msg)
    return extract_sql_from_response(raw)


def _is_only_db_access_question(message: str) -> bool:
    """True se il messaggio è solo una domanda tipo 'vedi il database?' (eventualmente con saluti)."""
    raw = message.strip().lower()
    # Rimuovi saluti comuni all'inizio
    for prefix in ("ciao, ", "ciao ", "salve, ", "salve ", "buongiorno, ", "buonasera, "):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :].strip()
    raw = raw.rstrip("?!.").strip()
    return any(
        raw == p.rstrip("?!.") or raw == p or p in raw
        for p in ("vedi il database", "vedi il db", "hai accesso al database", "hai accesso al db", "puoi vedere il database", "vedi i dati")
    ) and len(raw) < 80


def chat_with_llm(
    settings: Settings,
    project_md: str,
    policy_md: str,
    user: dict,
    message: str,
    app_url: str | None = None,
    db_schema: str | None = None,
    repo_code: str | None = None,
    project_manifest: str | None = None,
) -> str:
    # Domanda solo "vedi il database?" / "hai accesso al database?" → risposta fissa, nessuna chiamata LLM
    if settings.db_dsn and _is_only_db_access_question(message):
        return _DB_ACCESS_FIXED_ANSWER

    # Configurato se: base_url (locale Ollama, anche host.docker.internal) oppure api_key (cloud)
    has_base = bool(settings.llm_base_url and settings.llm_base_url.strip())
    if not has_base and not settings.llm_api_key:
        return (
            "IA non configurata. Per LLM locale avvia Ollama (ollama run llama3.2:3b) e imposta "
            "DEVIA_LLM_BASE_URL=http://localhost:11434/v1 (o host.docker.internal:11434 se il backend è in Docker). "
            "Per cloud imposta DEVIA_LLM_API_KEY."
        )

    system = build_system_prompt(
        project_md, policy_md, user, app_url, db_schema, repo_code=repo_code, project_manifest=project_manifest,
        assistant_name=getattr(settings, "name", "Kira"),
    )
    user_message = _build_user_message_for_llm(message.strip(), user)
    # Chiamata semplice al modello: l'orchestrazione dei tool viene gestita
    # dal backend (intent → chiamata API Laravel) e non tramite tools OpenAI.
    return _call_llm(settings, system, user_message)
