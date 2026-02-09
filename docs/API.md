# Riferimento API DevIA

Base URL di default (Docker): `http://localhost:8787`

## Autenticazione

Attualmente gli endpoint non richiedono autenticazione. In produzione si può aggiungere API key o token (header o query) e validarli in FastAPI.

---

## GET /health

Verifica rapida dello stato del servizio: istruzioni, DB e LLM (configurazione e check reali).

**Risposta** (200):

```json
{
  "ok": true,
  "service": "DevIA",
  "has_project_md": true,
  "has_policy_md": true,
  "repo_mounted": true,
  "repo_code_loaded": false,
  "repo_code_length": 0,
  "db_configured": true,
  "db_ok": true,
  "llm_configured": true,
  "llm_ok": true,
  "llm_model": "mistral"
}
```

- `has_project_md`: contenuto presente in `project.md`
- `has_policy_md`: contenuto presente in `policy.md`
- `repo_mounted`: `DEVIA_REPO_PATH` impostato (path repo codice intranet)
- `repo_code_loaded`: true se è stato caricato almeno un file PHP da `/repo` (es. `app/Models`)
- `repo_code_length`: numero di caratteri di codice caricato (0 se mount assente o repo senza PHP Laravel)
- `db_configured`: DSN DB impostato
- `db_ok`: **check reale** — connessione al DB riuscita (ping)
- `llm_configured`: base URL o API key LLM impostati
- `llm_ok`: **check reale** — API LLM raggiungibile (con Ollama: GET /api/tags; con solo API key non viene fatta richiesta)
- `llm_model`: modello configurato (es. `mistral`, `llama3.2:3b`)

---

## GET /db/ping

Verifica la connessione al database configurato.

**Risposta** (200):

```json
{
  "ok": true
}
```

**Errori**:

- **500**: `DEVIA_DB_DSN` non configurato o DB non raggiungibile (dettaglio nel body).

---

## GET /repo/check

Verifica repo (modelli intranet caricati) e connessione DB in un’unica chiamata.

**Risposta** (200):

```json
{
  "ok": true,
  "repo_files_count": 70,
  "repo_files": ["app/Models/User.php", "app/Models/Department.php", ...],
  "repo_code_length": 79980,
  "db_configured": true,
  "db_ok": true
}
```

- `repo_files`: primi 50 file (app/Models/*.php) caricati da `/repo`
- `db_ok`: risultato del ping al DB (null se DB non configurato)

---

## POST /debug/context

Stesso body di `POST /chat`, ma **non chiama l’LLM**. Restituisce il contesto che verrebbe inviato (user, anteprima system prompt, schema DB) per verificare che i dati siano corretti e capire se un rifiuto viene dall’LLM.

**Body**: come per `POST /chat` (es. `user`, `message`, `conversation_id`, `app_url`).

**Risposta** (200):

```json
{
  "user_received": { "id": "123", "name": "Mario", "email": "mario@..." },
  "message": "dammi i dati su di me",
  "db_schema_loaded": true,
  "db_schema_length": 5000,
  "db_schema_preview": "tabelle e colonne...",
  "system_prompt_length": 3500,
  "system_prompt_preview": "Sei DevIA... === DATI UTENTE ...",
  "llm_model": "llama3.2:3b"
}
```

Usare questo endpoint per confermare che user e schema DB sono presenti nel prompt; se sì e l’LLM risponde comunque «non posso accedere ai dati», il blocco è del modello (vedi [Configurazione – Modelli LLM](CONFIGURATION.md#modelli-llm-consigliati)).

---

## POST /chat

Invia un messaggio al chatbot e riceve la risposta.

**Body** (JSON):

| Campo             | Tipo   | Obbligatorio | Descrizione                          |
|-------------------|--------|--------------|--------------------------------------|
| `user`            | object | sì           | Dati utente (es. id, nome, ruoli)   |
| `message`         | string | sì           | Testo del messaggio (non vuoto)     |
| `conversation_id` | string | no           | ID conversazione per contesto       |

**Esempio**:

```json
{
  "user": { "id": "123", "name": "Mario" },
  "message": "Come richiedo le ferie?",
  "conversation_id": "conv-abc-001"
}
```

**Risposta** (200):

```json
{
  "type": "message",
  "assistant": "DevIA",
  "message": "DevIA operativo. Ho caricato istruzioni progetto: SI, policy: SI. Mi hai scritto: Come richiedo le ferie?"
}
```

- `type`: tipo di risposta (es. `"message"`; in futuro potrebbero esserci `tool_call`, `action`, ecc.).
- `assistant`: nome del servizio.
- `message`: testo di risposta.

**Errori**:

- **422**: `message` vuoto o assente (dettaglio nel body).

---

## Formato risposta chat (evoluzione)

In futuro la risposta potrà includere:

- `type: "tool_call"` o `type: "action"`: richiesta di esecuzione di un’operazione verso Laravel (con conferma utente).
- Campi aggiuntivi per RAG (es. riferimenti a file/repo) o per conversazioni persistenti.

Il plugin Laravel dovrà gestire questi tipi quando verranno introdotti.
