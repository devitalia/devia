# DevIA – Plugin Laravel

Plugin Laravel per **DevIA**: widget **invisibile** nelle pagine, attivazione con la voce **"ehi DevIa"**, apertura sessione (utente + DB/repo lato DevIA) e chat **solo testuale**.

## Requisiti

- PHP 8.2+
- Laravel 10 o 11
- Guzzle (per chiamate HTTP a DevIA)

## Installazione

Guida dettagliata: **[INSTALLAZIONE_LARAVEL.md](INSTALLAZIONE_LARAVEL.md)** (in questa cartella).

### Da repository GitHub (questo repo – plugin alla root)

Il plugin è alla **root** del repo DevIA. Nel `composer.json` del progetto Laravel:

```json
"repositories": [
    {
        "type": "vcs",
        "url": "https://github.com/TUO-USER-O-ORG/devia"
    }
],
"require": {
    "devia/plugin-laravel": "dev-main"
}
```

Poi: `composer update devia/plugin-laravel`.

### Con path locale (repo DevIA clonato)

Se hai clonato il repo DevIA, il plugin è alla root. Usa il path alla **root** del repo:

```json
"repositories": [
    { "type": "path", "url": "../devia" }
],
"require": {
    "devia/plugin-laravel": "@dev"
}
```

Poi: `composer update devia/plugin-laravel`.

### Dopo l’installazione (in entrambi i casi)

1. Pubblica config e asset:
   ```bash
   php artisan vendor:publish --tag=devia-config
   php artisan vendor:publish --tag=devia-assets
   ```

2. Configura in `.env`:
   ```env
   DEVIA_API_URL=http://localhost:8787
   DEVIA_VOICE_TRIGGER=ehi devia
   ```

3. Nel layout (es. prima di `</body>`):
   ```blade
   @devia
   ```

## Comportamento

- **Invisibile**: in pagina non si vede nulla; lo script è in ascolto (Web Speech API, microfono).
- **"ehi DevIa"**: pronunciando la frase (o quella in `DEVIA_VOICE_TRIGGER`) si apre la sessione:
  - `GET /devia/session` → dati utente (auth Laravel) + `conversation_id`.
  - Appare il pannello chat.
- **Chat testuale**: l’utente scrive; ogni messaggio va a `POST /devia/chat`; Laravel inoltra a DevIA con user, message, conversation_id. DevIA risponde usando DB e repo (configurati lato deploy); la risposta viene mostrata in chat.

### Vedere la chiamata (debug)

Per ispezionare il contesto inviato all'LLM (system prompt, dati utente, messaggio, schema DB) **senza** effettuare la chiamata alla chat, usa:

- **POST /devia/debug-context** — stesso body di `POST /devia/chat` (`message` obbligatorio, `conversation_id` opzionale). La risposta contiene `user_received`, `system_prompt_preview`, `message`, `db_schema_preview`, `llm_model`, ecc. (vedi [API.md](API.md) – endpoint `POST /debug/context` del backend).

Esempio con curl (sostituisci base URL e messaggio):

```bash
curl -X POST http://localhost:8000/devia/debug-context \
  -H "Content-Type: application/json" \
  -H "Cookie: ..." \
  -d '{"message":"chi sono?"}'
```

## Config

| Variabile | Descrizione |
|-----------|-------------|
| `DEVIA_API_URL` | URL base del servizio DevIA (es. `http://localhost:8787`) |
| `DEVIA_CHAT_TIMEOUT` | Timeout in secondi per la chiamata a DevIA (default: 120; utile se l’LLM è lento) |
| `DEVIA_VOICE_TRIGGER` | Frase vocale per aprire la sessione (default: `ehi devia`) |
| `DEVIA_LARAVEL_TOOL_TOKEN` | (Futuro) Token per chiamate da DevIA al sito |

## Route

- `GET /devia/session` – Apertura sessione: restituisce user e conversation_id (usa auth Laravel).
- `POST /devia/chat` – Invia messaggio a DevIA (proxy con user dalla sessione).
- `POST /devia/debug-context` – Restituisce il contesto che verrebbe inviato all'LLM (system prompt, user, message, schema DB) senza chiamare la chat; utile per vedere la chiamata in debug.

## Licenza

MIT
