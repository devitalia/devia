# Deploy DevIA

## Docker

Il servizio è containerizzato. Build e avvio:

```bash
docker compose up -d devia
```

- **Porta**: 8787 (mappata su host).
- **Health**: `GET http://localhost:8787/health`.

### Dockerfile

- Base: `python:3.11-slim`
- Porta esposta: 8787
- Comando: `uvicorn app.main:app --host 0.0.0.0 --port 8787`

### Docker Compose (essenziale)

```yaml
services:
  devia:
    build: ./devia
    container_name: devia
    env_file: .env
    environment:
      DEVIA_NAME: DevIA
      DEVIA_INSTRUCTIONS_PATH: /instructions
      DEVIA_DB_DSN: ${CHATBOT_DB_RO_DSN}
      DEVIA_LARAVEL_BASE_URL: http://app
      DEVIA_LARAVEL_TOOL_TOKEN: ${CHATBOT_TOOL_TOKEN}
    volumes:
      - ./chatbot/instructions:/instructions:ro
      - ./:/repo:ro
    ports:
      - "8787:8787"
```

- **Istruzioni**: `./chatbot/instructions` → `/instructions` (read-only).
- **Repo**: `./` → `/repo` (read-only, per RAG futuro).
- **DB**: DSN da `.env` (`CHATBOT_DB_RO_DSN`). Se il DB è in un altro stack, assicurarsi che la rete Docker permetta a `devia` di raggiungere il host/porta del DB.

### Dipendenza da DB

Se il DB è definito nello stesso `docker-compose.yml`:

```yaml
devia:
  # ...
  depends_on:
    - db
```

Non garantisce che il DB sia già pronto ad accettare connessioni; in produzione conviene usare healthcheck sul servizio `db` o retry in DevIA.

## Variabili d’ambiente (produzione)

- **DEVIA_DB_DSN**: usare un utente **read-only** e un DSN che punti al DB raggiungibile dalla rete del container (nome servizio o host reale).
- **DEVIA_LARAVEL_BASE_URL**: URL con cui il container DevIA raggiunge l’app Laravel (nome servizio in Compose, es. `http://app`, o URL pubblico se fuori dalla stessa rete).
- **DEVIA_LARAVEL_TOOL_TOKEN** / **CHATBOT_TOOL_TOKEN**: valore lungo e casuale, condiviso solo con il plugin Laravel per le chiamate tool.

Non committare `.env`; usare `.env.example` come schema senza segreti.

## Esecuzione locale (senza Docker)

1. Python 3.11+, virtualenv consigliato.
2. `pip install -r devia/requirements.txt`
3. Impostare le variabili d’ambiente (o un `.env` caricato con `python-dotenv` se aggiunto al bootstrap).
4. Montare le istruzioni: es. copiare `chatbot/instructions` in una cartella e impostare `DEVIA_INSTRUCTIONS_PATH` al path assoluto.
5. Avvio: dalla root `devia`:  
   `uvicorn app.main:app --host 0.0.0.0 --port 8787`

## Coesistenza con Laravel

Se Laravel è nello stesso Compose (es. servizio `app`):

- `DEVIA_LARAVEL_BASE_URL=http://app` (o lo stesso hostname usato per le chiamate HTTP tra container).
- Il plugin sul sito Laravel deve puntare all’URL di DevIA raggiungibile dal browser (es. `http://localhost:8787` o un dominio esposto con reverse proxy).

## Sicurezza

- Esporre la porta 8787 solo dove necessario; in produzione usare reverse proxy (nginx/traefik) con HTTPS.
- Valutare autenticazione sulle API DevIA (API key, JWT, ecc.) e restrizione IP se il servizio è interno.
- DB: solo utente read-only per DevIA; token Laravel custodito in env e non in repo.
