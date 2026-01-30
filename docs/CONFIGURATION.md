# Configurazione DevIA

## Variabili d’ambiente

DevIA legge la configurazione da variabili d’ambiente. In Docker Compose possono essere definite in `environment` o tramite `env_file: .env`.

| Variabile | Obbligatorio | Default | Descrizione |
|-----------|--------------|---------|-------------|
| `DEVIA_NAME` | no | `DevIA` | Nome del servizio (usato nelle risposte chat). |
| `DEVIA_INSTRUCTIONS_PATH` | no | `/instructions` | Path della directory che contiene `project.md` e `policy.md`. In Docker è tipicamente un volume montato (es. `./chatbot/instructions:/instructions:ro`). |
| `DEVIA_DB_DSN` | condizionale | — | DSN di connessione al DB read-only. Per Docker Compose si usa spesso `CHATBOT_DB_RO_DSN` nel file `.env` e si mappa in `DEVIA_DB_DSN`. Richiesto per `/db/ping` e per uso futuro del DB in chat. |
| `DEVIA_LARAVEL_BASE_URL` | no | — | URL base dell’app Laravel (es. `http://app`) per future chiamate di azioni/tool. |
| `DEVIA_LARAVEL_TOOL_TOKEN` | no | — | Token per autenticare le chiamate da DevIA verso Laravel. In `.env` spesso come `CHATBOT_TOOL_TOKEN`. |

### Esempio `.env` (minimo)

```env
CHATBOT_DB_RO_DSN=mysql://chatbot_ro:chatbot_pass@db:3306/intranet
CHATBOT_TOOL_TOKEN=superlongtoken
```

Nel `docker-compose.yml` si mappano in `DEVIA_DB_DSN` e `DEVIA_LARAVEL_TOOL_TOKEN` come nell’esempio in [Deploy](DEPLOYMENT.md).

---

## Istruzioni per l’IA

Le istruzioni sono file Markdown nella directory `DEVIA_INSTRUCTIONS_PATH`:

- **project.md**: contesto del progetto (cosa fa il sito, funzionalità, procedure). È la “fonte” per rispondere su uso dell’intranet, procedure, configurazioni.
- **policy.md**: regole di comportamento (non rivelare segreti, non inventare dati, conferma per azioni, chiedere chiarimenti se ambiguo).

DevIA carica entrambi i file a ogni richiesta chat (e per `/health`). Se un file manca o è vuoto, il relativo contenuto sarà stringa vuota.

### Esempio `project.md`

```markdown
# Progetto: Intranet HR

DevIA aiuta l'utente con:
- uso funzionalità intranet
- procedure (ferie, permessi, presenze)
- spiegazioni configurazioni aziendali

Fonte verità per regole: database (tabelle impostazioni).
```

### Esempio `policy.md`

```markdown
# Policy DevIA

- Non rivelare segreti (password, token, .env).
- Non inventare dati: se mancano informazioni, chiedere.
- Azioni che modificano dati: solo dopo conferma esplicita dell'utente.
- Se una richiesta è ambigua, chiedere chiarimenti.
```

Adatta `project.md` e `policy.md` al singolo sito/progetto; il plugin Laravel può coesistere con più istanze DevIA (o più set di istruzioni) se servi più progetti.

---

## Database

- **Ruolo**: read-only. DevIA lo usa per impostazioni e contesto (e in futuro per arricchire le risposte).
- **DSN**: formato MySQL `mysql://user:password@host:port/database` (porta tipica 3306).
- **Sicurezza**: usare un utente DB con soli permessi di lettura (`chatbot_ro` nell’esempio).

---

## Repository e RAG (futuro)

Il mount del repo in `/repo` (es. `./:/repo:ro` in Docker) è pensato per un uso futuro di RAG sul codice. La configurazione non richiede altre variabili; il path è fisso nel volume. Il plugin Laravel e i siti possono usare lo stesso repo GitHub per allineare contesto codice e risposte dell’IA.
