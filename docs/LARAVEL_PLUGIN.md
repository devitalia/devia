# Integrazione plugin Laravel

## Ruolo del plugin

Il **plugin Laravel** viene installato nei siti che usano DevIA. Fa da ponte tra:

- **Utente** (UI chat / comandi nel sito)
- **DevIA** (servizio API che elabora messaggi e fornisce istruzioni/operazioni)
- **Contesto del sito**: repository GitHub e database a cui il sito ha accesso

L’IA può così rispondere in modo corretto e coerente con dati e codice del progetto.

## Comportamento (modalità attuale)

- **Invisibile**: il plugin è presente nelle pagine ma non mostra alcun elemento visibile.
- **Attivazione vocale**: quando l’utente pronuncia **"ehi DevIa"** (o la frase configurata in `DEVIA_VOICE_TRIGGER`), si apre la **sessione**.
- **Sessione**: il plugin chiama `GET /devia/session`, ottiene i dati utente (dal DB/auth Laravel) e un `conversation_id`, e si prepara a rispondere.
- **Chat testuale**: l’utente scrive messaggi; il plugin invia a Laravel `POST /devia/chat`, che inoltra a DevIA con `user`, `message`, `conversation_id`. DevIA usa DB e repo (configurati lato deploy) e risponde; la risposta viene mostrata in chat.

## Installazione e uso (plugin alla root del repo)

1. Includere il package nell’app Laravel (es. via path locale o Composer).
2. Pubblicare config e asset: `php artisan vendor:publish --tag=devia-config` e `--tag=devia-assets`.
3. Configurare in `.env`: `DEVIA_API_URL` (URL DevIA), opzionale `DEVIA_VOICE_TRIGGER` (default `ehi devia`).
4. Inserire il widget (invisibile) in un layout condiviso, es. prima di `</body>`: `@devia` oppure `@include('devia::widget')`.

Il widget non occupa spazio e non è cliccabile fino al trigger vocale; dopo "ehi DevIa" appare il pannello chat e l’utente può scrivere in modalità testuale.

## Flusso tipico

1. Pagina con `@devia`: script invisibile in ascolto (Web Speech API).
2. Utente dice "ehi DevIa" → apertura sessione: `GET /devia/session` → user + `conversation_id`.
3. Utente scrive nel widget chat; il plugin invia `POST /devia/chat` (Laravel inoltra a DevIA con user, message, conversation_id).
4. DevIA usa istruzioni, DB, (futuro) repo e risponde; la risposta viene mostrata in chat.

## Cosa deve fare il plugin (lato sito)

- **Chiamare DevIA**: conoscere l’URL base del servizio DevIA (configurabile, es. `DEVIA_API_URL`) e inviare `POST /chat` con payload JSON.
- **Gestire risposta**: interpretare `type` e `message` (e in futuro `tool_call`/`action`) e aggiornare la UI.
- **Accesso a repo e DB**: il sito ha già accesso al repo GitHub e al database; DevIA può avere lo stesso DB (read-only) e, in futuro, contesto da repo (RAG). Il plugin non deve “passare” il repo/DB a DevIA in ogni richiesta: DevIA è configurato con DSN e mount repo in deploy.
- **Conversazioni**: inviare lo stesso `conversation_id` per messaggi della stessa conversazione, quando DevIA supporterà contesto multi-turno.

## Configurazione lato DevIA per Laravel

Per permettere a DevIA di chiamare il sito Laravel (azioni/tool in futuro):

- **DEVIA_LARAVEL_BASE_URL**: URL base dell’app Laravel (es. `http://app` in Docker, o l’URL pubblico).
- **DEVIA_LARAVEL_TOOL_TOKEN**: token segreto condiviso; il plugin (o un middleware) espone endpoint che verificano questo token per le chiamate in arrivo da DevIA.

Il plugin può definire route protette (es. `POST /devia/tool/execute`) che:

1. Verificano l’header (es. `X-DevIA-Token`) contro `CHATBOT_TOOL_TOKEN`.
2. Eseguono l’azione richiesta (solo dopo eventuale conferma utente gestita da DevIA/UI).
3. Restituiscono esito a DevIA.

## Riepilogo

| Componente | Responsabilità |
|------------|----------------|
| **Plugin Laravel** | Widget invisibile, trigger "ehi DevIa", sessione (user + conversation_id), UI chat testuale, proxy verso DevIA, (futuro) endpoint per azioni con token |
| **DevIA** | Elaborazione messaggi, istruzioni, DB, (futuro) RAG e chiamate verso Laravel |
| **Repo GitHub + DB** | Fonte di verità condivisa; sito e DevIA (in deploy) vi accedono per risposte coerenti |

La documentazione del plugin Laravel (nel suo repo) dovrebbe descrivere: variabili di configurazione (`DEVIA_API_URL`, `CHATBOT_TOOL_TOKEN`), formato della richiesta/risposta chat e, quando previsto, formato delle chiamate tool da DevIA verso il sito.
