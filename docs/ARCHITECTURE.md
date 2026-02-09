# Architettura DevIA

## Panoramica

DevIA è un **servizio API generico** che espone un **chatbot**. Il chatbot:

1. **Riceve comandi** dal front-end (siti Laravel tramite plugin).
2. **Fornisce istruzioni** basate su contesto di progetto (`project.md`), policy (`policy.md`) e dati dal database.
3. **Può elaborare operazioni** (in evoluzione: tool/azioni verso Laravel, RAG su codice).

Fa coppia con un **plugin Laravel** installato nei siti: i siti hanno accesso al **repository GitHub** e al **database** relativo, così l’IA può rispondere correttamente a tutte le richieste.

## Componenti

```
┌─────────────────────────────────────────────────────────────────┐
│  Sito Laravel (con plugin DevIA)                                 │
│  - UI chat / comandi                                             │
│  - Accesso repo GitHub + DB                                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP (chat, eventuali azioni)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  DevIA (questo servizio)                                         │
│  - FastAPI (health, db/ping, chat)                               │
│  - Istruzioni: project.md, policy.md                             │
│  - DB read-only (impostazioni, contesto)                         │
│  - (futuro) Chiamate a Laravel per azioni                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   MySQL               Volume /instructions   (futuro) Laravel
   (read-only)        + /repo per RAG        API con token
```

## Flusso chat

1. **Utente** invia un messaggio dalla UI del sito (gestita dal plugin Laravel).
2. **Plugin Laravel** chiama `POST /chat` su DevIA con `user`, `message`, opzionalmente `conversation_id`.
3. **DevIA**:
   - carica istruzioni da `project.md` e `policy.md`;
   - (attuale) risponde in modo demo mostrando stato istruzioni;
   - (futuro) userà DB per impostazioni, RAG su repo, e potrà proporre tool/azioni verso Laravel.
4. La **risposta** torna al plugin e viene mostrata all’utente.

## Integrazione con Laravel

- **Plugin Laravel**: inserito nei siti, invia le richieste chat a DevIA e (in futuro) può esporre endpoint per azioni richieste da DevIA.
- **DevIA** è configurato con `DEVIA_LARAVEL_BASE_URL` e `DEVIA_LARAVEL_TOOL_TOKEN` per chiamate autenticate verso l’app Laravel quando serviranno operazioni lato sito.

## Uso di GitHub e database

- **Repository GitHub**: il contesto codice può essere montato in DevIA (es. volume `./:/repo:ro`) per RAG futuro; il plugin/sito può avere accesso allo stesso repo per coerenza.
- **Database**: DevIA usa un DSN read-only (`DEVIA_DB_DSN` / `CHATBOT_DB_RO_DSN`) per leggere impostazioni e dati; il sito Laravel condivide lo stesso DB (o uno collegato) così l’IA ha la stessa “fonte di verità” per rispondere alle richieste.

## Estensioni previste

- **Tool/azioni**: proposta di azioni (es. “crea richiesta ferie”) con conferma utente e chiamata API Laravel.
- **RAG su codice**: indicizzazione del repo montato in `/repo` per risposte basate su codice.
- **Conversazioni**: uso di `conversation_id` per contesto multi-turno e eventuale persistenza.

### MCP (Model Context Protocol) come evoluzione

Oggi il contesto (user, project.md, schema DB) viene iniettato nel system prompt. Per domande su **codice** non c’è ancora accesso ai file del repo.

Un’evoluzione possibile è usare **MCP** per dare al bot accesso dinamico a codice e database:

1. **Laravel (o servizio dedicato) espone un server MCP** con tool tipo: `read_file`, `search_code`, `query_db` (read-only).
2. **DevIA** agisce da client MCP: in base alla domanda dell’utente, (a) chiama i tool MCP per recuperare contesto (file, risultati query), (b) inietta il risultato nel prompt e chiama l’LLM.
3. In alternativa, l’**LLM** può avere tool-calling: gli si passano i tool MCP come “funzioni” e il modello decide quando chiamare `read_file` / `query_db`; il backend esegue la chiamata e ripassa il risultato all’LLM.

In entrambi i casi il bot può rispondere a “come funziona il modulo ferie?” o “quali tabelle ci sono?” senza dover mettere l’intero repo nello prompt. La scelta è: contesto “gather” prima della chiamata LLM (più semplice) vs tool-calling dell’LLM (più flessibile, richiede modelli che supportano function calling).
