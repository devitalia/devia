# DevIA API

FastAPI avviabile con Docker. La home `/` apre direttamente Swagger (`/docs`).

## Endpoint attuali

- `GET /health` ping rapido.
- `GET /getddtdevtec` esegue login al portale COMET, apre `DDT e fatture`, clicca `Cerca`, apre i dettagli con `Visualizza`, importa testata+righe in SQLite e scarica il PDF.
- `GET /getddtdevtec/comet/state` lista i DDT COMET importati.
- `DELETE /getddtdevtec/comet/state/{progressive_id}` cancella un DDT importato (e prova a cancellare i file CSV/PDF locali).
- `GET /getddtdevtec/state` lista i record processati nel DB SQLite.
- `GET /getddtdevtec/email/sync` elabora nuove email abilitate in `senders.yaml`, legge CSV/PDF allegati e invia i record all'intranet.
- `GET /getddtdevtec/email/sonepar/replay` ripassa storico email Sonepar e, in base a `dry_run`, simula o applica riallineamento verso intranet solo per DDT con incoerenze riga (`quantita`, `importo`, `prezzo_unitario`).
- `DELETE /getddtdevtec/state/{progressive_id}` cancella un record tramite progressivo (`rowid` SQLite).
- `POST /features/echo` endpoint test (menu `EAGLE` in Swagger).
- `GET /eagle/health` endpoint base dedicato cliente EAGLE.
- `POST /eagle/echo` endpoint test dedicato cliente EAGLE.

## Configurazione mail

1. Copia `.env.example` in `.env` e imposta almeno:
   - `MAIL_USERNAME`
   - `MAIL_PASSWORD`
   - `MAIL_IMPORT_SINCE=2026-01-01` (filtro minimo data email)
   - `MAIL_FIRST_IMPORT_FULL_SCAN=true` (al primo run prende tutte le email dal `MAIL_IMPORT_SINCE`)
2. Modifica `config/senders.yaml` per la lista mittenti e requisiti attachment (`require_csv`, `require_pdf`) e codice fornitore intranet (`supplier_id`).

## Configurazione COMET

Imposta in `.env`:

- `COMET_BASE_URL=https://www.gruppocomet.it`
- `COMET_USERNAME=...`
- `COMET_PASSWORD=...`
- `COMET_SUPPLIER_CODE=...` (codice fornitore fisso da inviare all'intranet; se vuoto usa `COMET_USERNAME`)
- `COMET_DOWNLOAD_DIR=data/downloads`
- `COMET_IMPORT_SINCE=2026-01-01` (filtro minimo data DDT in ricerca COMET)
- `INTRANET_API_URL=...`
- `INTRANET_API_TOKEN=...`
- `INTRANET_SEND_PDF_BASE64=true` (se `true`, invia anche il PDF codificato base64 nel payload)

Per ogni DDT importato viene creato un payload JSON pronto per l'invio all'intranet:

- `intranet_payload.testata`
- `intranet_payload.righe`

## Avvio rapido

```bash
cp .env.example .env
docker compose up --build -d
```

Apri [http://localhost:8787](http://localhost:8787) per Swagger UI.

## Esecuzione produzione (da scheduler esterno)

In produzione la sincronizzazione puo essere chiamata da scheduler esterno (es. Cronicle) via API:

- `GET /getddtdevtec/initial-import` esegue import iniziale completa (COMET + email).
  - esclude il giorno corrente e importa fino a ieri.
- `GET /getddtdevtec/daily-sync` sincronizza solo il giorno precedente (COMET + email).
- Tutte le API `getddtdevtec` richiedono token (stesso valore di `INTRANET_API_TOKEN`), via:
  - query string `?token=...`, oppure
  - header `Authorization: Bearer ...`.

## CI/CD GitHub + Kubernetes

Su push su `main`, il workflow `.github/workflows/cicd-k8s.yml` esegue:

- build Docker image;
- push su GHCR (`ghcr.io/devitalia/devia:latest` e `ghcr.io/devitalia/devia:sha-<commit>`);
- deploy diretto su Kubernetes con `kubectl set image` e verifica rollout.

Secrets richiesti nel repository GitHub:

- `GHCR_USERNAME`: utente/owner con permesso push su `ghcr.io/devitalia/devia`.
- `GHCR_TOKEN`: token GitHub con scope `write:packages` (e `read:packages`).
- `KUBE_CONFIG`: kubeconfig completo del cluster target.
- `K8S_NAMESPACE`: namespace target (default suggerito: `default`).
- `K8S_DEPLOYMENT_NAME`: deployment da aggiornare (default suggerito: `devia-api`).
- `K8S_CONTAINER_NAME`: nome container nel deployment (default suggerito: `api`).
- `K8S_ENV_FILE`: contenuto completo del file `.env` produzione (multiline secret).
- `K8S_ENV_SECRET_NAME` (opzionale): nome Secret Kubernetes da creare/aggiornare (default `devia-env`).

Il deploy Kubernetes sincronizza automaticamente il secret runtime da `K8S_ENV_FILE`:

- crea/aggiorna il Secret Kubernetes (`devia-env` di default) da env-file;
- applica le variabili al deployment con `kubectl set env --from=secret/...`;
- aggiorna immagine e verifica rollout.

## Verifiche

```bash
curl http://localhost:8787/health
curl http://localhost:8787/getddtdevtec
curl http://localhost:8787/getddtdevtec/comet/state
curl -X DELETE http://localhost:8787/getddtdevtec/comet/state/1
curl http://localhost:8787/getddtdevtec/state
curl -X DELETE http://localhost:8787/getddtdevtec/state/1
```

## Stato locale ingestione

- DB deduplica: `data/mail_state.db`
- Ultimo UID processato: tabella `state_meta` dentro SQLite (`key=last_email_uid`)

## Stop

```bash
docker compose down
```
