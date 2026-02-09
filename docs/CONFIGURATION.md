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
| `DEVIA_LLM_BASE_URL` | sì (locale) | `http://localhost:11434/v1` | Base URL dell’API. Per **LLM locale** usa Ollama: `http://localhost:11434/v1`. Nessuna chiave richiesta. |
| `DEVIA_LLM_MODEL` | no | `llama3.2:3b` | Nome modello. Con Ollama: vedi sotto [Modelli LLM consigliati](#modelli-llm-consigliati). |
| `DEVIA_LLM_API_KEY` | no (locale) | — | Solo per cloud (OpenAI/Azure). Con Ollama lasciare vuoto. |
| `DEVIA_DEBUG` | no | — | Se impostato (es. `1`), abilita log dettagliati (richieste chat, query SQL). Utile per debug. |
| `DEVIA_REPO_PATH` | no | `/repo` | Path del repo intranet (Laravel). In Docker è un volume (es. `../intranet/laravel:/repo:ro`). Usato solo se `DEVIA_REPO_MAX_CHARS` > 0. |
| `DEVIA_REPO_MAX_CHARS` | no | `0` | Caratteri massimi di codice da iniettare nel prompt (solo `app/Models/*.php`). **Default 0**: nessun codice in prompt; il contesto è schema DB + istruzioni; le risposte si ottengono eseguendo le query sul DB. Per aggiungere codice (es. per relazioni complesse) imposta un valore (es. `20000`). |

### Modelli LLM consigliati

DevIA deve **leggere il contesto** (dati utente dalla sessione, schema DB, istruzioni) e **rispondere o generare SQL** senza rifiuti generici («non posso accedere ai dati», «non mi connetto a database»). Alcuni modelli (soprattutto piccoli e molto “allineati”) ignorano il system prompt e rifiutano comunque.

**Verifica che il contesto arrivi all’LLM**: usa `POST /debug/context` con lo stesso body di `/chat`. Se in `system_prompt_preview` compaiono i dati utente e lo schema DB ma la chat continua a rifiutare, il blocco è del modello.

**Modelli Ollama da provare** (in ordine di priorità per “obbedienza” al prompt e uso con DB/sorgente):

| Modello | Comando | Note |
|--------|---------|------|
| **mistral** | `ollama run mistral` | Spesso rispetta bene il system prompt, meno rifiuti a priori. |
| **phi3** | `ollama run phi3` | Buon compromesso qualità/dimensione, utile per ragionamento. |
| **qwen2.5** | `ollama run qwen2.5:7b` | Ottimo instruction-following, adatto a contesto tecnico. |
| **llama3.2** (più grande) | `ollama run llama3.2:latest` o `llama3.2:1b` | La variante 3b a volte rifiuta; provare 1b o latest. |
| **deepseek-r1** | `ollama run deepseek-r1` | Orientato a ragionamento e istruzioni. |
| **gemma2** | `ollama run gemma2:9b` | Può essere meno restrittivo in contesti “sistema”. |

Dopo aver scaricato il modello, imposta in `.env` ad es. `DEVIA_LLM_MODEL=mistral` e riavvia il container.

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

## Repo e database: contesto ridotto, risposte “cercate”

Repo (git) e database sono condivisi **per far cercare le risposte**, non per avere tutto il progetto in contesto.

- **Default**: nessun codice del repo nel prompt (`DEVIA_REPO_MAX_CHARS=0`). In prompt vanno solo: istruzioni (`project.md`, `policy.md`), **schema DB** (tabelle/colonne da INFORMATION_SCHEMA), utente. L’LLM genera query SELECT in base allo schema; la query viene eseguita e il risultato usato per rispondere.
- **Opzionale**: se servono dettagli su relazioni o modelli Laravel, imposta `DEVIA_REPO_MAX_CHARS` (es. `20000`). DevIA caricherà fino a quel numero di caratteri da `app/Models/*.php` nel path `DEVIA_REPO_PATH` (default `/repo`). In Docker monta il repo Laravel, es. `- ../intranet/laravel:/repo:ro`.

Verifica: `GET /health` → `repo_code_length` (0 con default), `db_ok`, `db_configured`.
