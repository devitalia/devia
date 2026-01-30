# DevIA

Servizio API generico con chatbot che riceve comandi, fornisce istruzioni e può elaborare operazioni. Pensato per fare coppia con un **plugin Laravel** installato nei tuoi siti: il sito ha accesso al repository GitHub e al database relativo, così l’IA può rispondere correttamente a tutte le richieste.

## Cosa fa DevIA

- **Chatbot via API**: riceve messaggi dall’utente e risponde in base a istruzioni di progetto e policy.
- **Istruzioni contestuali**: carica `project.md` e `policy.md` dal path configurato (es. repo/chatbot).
- **Database read-only**: può interrogare un DB MySQL per impostazioni e dati di contesto.
- **Integrazione Laravel**: tramite plugin sui siti, può ricevere comandi e (in futuro) invocare azioni sull’app Laravel (URL + token).
- **Estensibilità**: preparato per RAG su codice (mount del repo) e per tool/azioni verso Laravel.

## Quick start

1. Copia `.env.example` in `.env` e imposta almeno:
   - `CHATBOT_DB_RO_DSN` (DSN DB read-only)
   - `CHATBOT_TOOL_TOKEN` (token per chiamate verso Laravel, se usi il plugin)
2. Personalizza le istruzioni in `chatbot/instructions/` (`project.md`, `policy.md`).
3. Avvia con Docker:

```bash
docker compose up -d devia
```

4. Verifica: `GET http://localhost:8787/health` e `POST http://localhost:8787/chat` con body JSON (vedi [API](docs/API.md)).

## Come procedere

Per avviare il backend e integrare il plugin Laravel nel tuo sito, segui la guida **[Come procedere](docs/COME_PROCEDERE.md)**:

1. Avviare DevIA (Docker o uvicorn).
2. Nel progetto Laravel: aggiungere il repo GitHub, `composer require devia/plugin-laravel`, publish config/asset, impostare `DEVIA_API_URL` in `.env`, inserire `@devia` nel layout.
3. Verificare in browser: dire “ehi DevIa” e usare la chat.

## Documentazione

| Documento | Contenuto |
|-----------|-----------|
| [Architettura](docs/ARCHITECTURE.md) | Architettura del servizio, flussi chat, integrazione Laravel e uso di GitHub/DB |
| [API](docs/API.md) | Riferimento endpoint (health, db/ping, chat) |
| [Configurazione](docs/CONFIGURATION.md) | Variabili d’ambiente, istruzioni (project.md, policy.md) |
| [Plugin Laravel](docs/LARAVEL_PLUGIN.md) | Come funziona l’integrazione con il plugin Laravel sui siti |
| [Come procedere](docs/COME_PROCEDERE.md) | Istruzioni operative: avviare DevIA e integrare il plugin Laravel |
| [Installazione Laravel](docs/INSTALLAZIONE_LARAVEL.md) | Dettaglio installazione plugin (da GitHub o path locale) |
| [Deploy](docs/DEPLOYMENT.md) | Docker, docker-compose e varianti di deploy |

## Struttura progetto

```
devia/
├── composer.json           # Package Laravel (devia/plugin-laravel) – installabile da GitHub
├── config/                 # Config plugin Laravel
├── src/                    # Provider e controller plugin Laravel
├── resources/              # View e JS del widget (voce “ehi DevIa”, chat)
├── routes/                 # Route /devia/session e /devia/chat
├── chatbot/instructions/  # Istruzioni per l’IA (project.md, policy.md)
├── devia/                  # Servizio FastAPI
│   ├── app/
│   │   ├── main.py         # Endpoint e logica chat
│   │   ├── config.py       # Settings da env
│   │   ├── db.py           # Connessione DB
│   │   └── instructions.py # Caricamento istruzioni
│   ├── Dockerfile
│   └── requirements.txt
├── docker-compose.yml
├── .env.example
└── docs/                   # Documentazione
```

## Requisiti

- Docker (per esecuzione container)
- MySQL (DSN in `.env`)
- Per integrazione completa: sito Laravel con plugin DevIA + accesso a repo GitHub e DB

## Licenza

Privato / uso interno.
