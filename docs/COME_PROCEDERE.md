# Come procedere

Istruzioni operative per avviare DevIA (backend) e integrare il plugin Laravel nel tuo sito.

---

## 1. Backend DevIA (servizio API)

Serve per elaborare i messaggi della chat. Puoi avviarlo in locale o in Docker.

### Con Docker (consigliato)

1. Dalla **root del repo** (dove c’è `docker-compose.yml`):

   ```bash
   cp .env.example .env
   ```

2. Modifica `.env` e imposta almeno:
   - `CHATBOT_DB_RO_DSN` – DSN del DB read-only (es. `mysql://user:pass@host:3306/dbname`)
   - `CHATBOT_TOOL_TOKEN` – token per future chiamate da DevIA verso Laravel (opzionale)

3. Avvia il servizio:

   ```bash
   docker compose up -d devia
   ```

4. Controlla che risponda:
   - `GET http://localhost:8787/health` → JSON con `ok: true`, `has_project_md`, `has_policy_md`, `db_configured`
   - Se il DB non è ancora pronto puoi comunque usare la chat; le risposte saranno limitate.

### Senza Docker (solo Python)

1. Crea un virtualenv e installa le dipendenze:

   ```bash
   cd devia
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Imposta le variabili d’ambiente (dalla root del repo, dove c’è `.env`):

   - `DEVIA_INSTRUCTIONS_PATH` – path alle istruzioni (es. `../chatbot/instructions` se parti da `devia/`)
   - `DEVIA_DB_DSN` – DSN DB (opzionale)

3. Avvia:

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8787
   ```

L’URL del backend che userai nel plugin Laravel è: **`http://localhost:8787`** (o l’URL reale se lo esponi altrove).

---

## 2. Plugin Laravel nel tuo progetto

Per avere il widget “ehi DevIa” e la chat nel sito Laravel.

### 2.1 Installa il package

Nel **progetto Laravel** (non in questo repo):

1. Apri `composer.json` e aggiungi il repository e la dipendenza (sostituisci con l’URL del tuo repo DevIA):

   ```json
   {
       "repositories": [
           {
               "type": "vcs",
               "url": "https://github.com/TUO-USER-O-ORG/devia"
           }
       ],
       "require": {
           "devia/plugin-laravel": "dev-main"
       }
   }
   ```

2. Installa:

   ```bash
   composer update devia/plugin-laravel
   ```

Guida dettagliata (path locale, tag, ecc.): [INSTALLAZIONE_LARAVEL.md](INSTALLAZIONE_LARAVEL.md).

### 2.2 Pubblica config e asset

Sempre nel progetto Laravel, una sola volta:

```bash
php artisan vendor:publish --tag=devia-config
php artisan vendor:publish --tag=devia-assets
```

### 2.3 Configura `.env` (Laravel)

Nel `.env` dell’app Laravel:

```env
DEVIA_API_URL=http://localhost:8787
DEVIA_VOICE_TRIGGER=ehi devia
```

- `DEVIA_API_URL`: deve essere l’URL del backend DevIA (quello avviato al punto 1).
- In produzione usa l’URL reale (es. `https://devia.tuodominio.it`).

### 2.4 Inserisci il widget nel layout

Nel layout Blade usato dalle pagine dove vuoi DevIA (es. `resources/views/layouts/app.blade.php`), prima di `</body>`:

```blade
@devia
```

Salva. Il widget è invisibile fino a quando l’utente non dice “ehi DevIa” (o la frase in `DEVIA_VOICE_TRIGGER`).

---

## 3. Verifica end-to-end

1. **Backend**: DevIA in esecuzione (Docker o uvicorn) e risponde a `GET http://localhost:8787/health`.
2. **Laravel**: sito avviato (`php artisan serve` o il tuo ambiente), con `@devia` nel layout e `DEVIA_API_URL` che punta al backend.
3. **Browser**: apri una pagina del sito, concedi l’accesso al microfono se richiesto, di’ **“ehi DevIa”** → deve aprirsi il pannello chat; scrivi un messaggio e verifica che arrivi la risposta da DevIA.

Se la chat non si apre: controlla che il browser supporti il riconoscimento vocale (Chrome/Edge) e che la pagina sia servita via HTTPS o `localhost`. Se il messaggio non riceve risposta: controlla `DEVIA_API_URL` e che il backend sia raggiungibile dall’app Laravel (stessa rete / CORS se necessario).

---

## Riepilogo ordine

| Step | Dove | Cosa fare |
|------|------|-----------|
| 1 | Repo DevIA | Copiare `.env.example` in `.env`, configurare DSN e avviare `docker compose up -d devia` (o uvicorn) |
| 2 | Progetto Laravel | Aggiungere repo VCS e `require devia/plugin-laravel`, poi `composer update devia/plugin-laravel` |
| 3 | Progetto Laravel | `php artisan vendor:publish --tag=devia-config --tag=devia-assets` |
| 4 | Progetto Laravel | Impostare `DEVIA_API_URL` (e opzionale `DEVIA_VOICE_TRIGGER`) in `.env` |
| 5 | Progetto Laravel | Inserire `@devia` nel layout prima di `</body>` |
| 6 | Browser | Aprire il sito, dire “ehi DevIa” e provare la chat |
