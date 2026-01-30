# Riferimento API DevIA

Base URL di default (Docker): `http://localhost:8787`

## Autenticazione

Attualmente gli endpoint non richiedono autenticazione. In produzione si può aggiungere API key o token (header o query) e validarli in FastAPI.

---

## GET /health

Verifica rapida dello stato del servizio: istruzioni caricate e presenza DSN DB.

**Risposta** (200):

```json
{
  "ok": true,
  "service": "DevIA",
  "has_project_md": true,
  "has_policy_md": true,
  "db_configured": true
}
```

- `has_project_md`: contenuto presente in `project.md`
- `has_policy_md`: contenuto presente in `policy.md`
- `db_configured`: `DEVIA_DB_DSN` (o `CHATBOT_DB_RO_DSN`) impostato

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
