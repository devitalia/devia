# Integrare il plugin DevIA nel tuo progetto Laravel

Guida passo-passo per caricare il plugin dal repository GitHub e configurarlo nell’app Laravel.

---

## 1. Installazione del package

Il plugin è alla **root** del repo DevIA (`composer.json`, `config/`, `src/`, `resources/`, `routes/`), quindi puoi installarlo direttamente da GitHub. Hai due possibilità.

### Opzione A – Direttamente da GitHub (consigliata)

1. Nel tuo progetto Laravel apri `composer.json`.

2. Aggiungi il repository VCS con l’URL del repo DevIA (sostituisci con il tuo):

```json
{
    "repositories": [
        {
            "type": "vcs",
            "url": "https://github.com/TUO-USER-O-TUO-ORG/devia"
        }
    ],
    "require": {
        "devia/plugin-laravel": "dev-main"
    }
}
```

- Per usare un branch diverso da `main`: `"devia/plugin-laravel": "dev-nome-branch"`.
- Per usare un tag (es. `v1.0.0`): `"devia/plugin-laravel": "^1.0"` (dopo aver creato il tag su GitHub).

3. Installa/aggiorna:

```bash
composer update devia/plugin-laravel
```

Composer clona il repo e usa il `composer.json` alla root; il file `.gitattributes` esclude dal pacchetto le parti non-Laravel (`devia/`, `docs/`, `chatbot/`, ecc.), così in `vendor/devia/plugin-laravel/` trovi solo il plugin.

Il provider Laravel (`Devia\Plugin\DeviaServiceProvider`) viene registrato in automatico tramite `extra.laravel.providers` nel `composer.json` del plugin.

---

### Opzione B – Path locale (repo clonato)

Se hai già clonato il repo DevIA in locale:

1. Nel `composer.json` del **progetto Laravel** aggiungi un repository di tipo `path` che punta alla **root** del repo DevIA:

```json
{
    "repositories": [
        {
            "type": "path",
            "url": "../devia"
        }
    ],
    "require": {
        "devia/plugin-laravel": "@dev"
    }
}
```

- Regola `../devia` in base al percorso reale (es. `./devia` se la cartella è dentro il progetto).

2. Installa:

```bash
composer update devia/plugin-laravel
```

---

## 2. Pubblicare config e asset

Dopo l’installazione, una sola volta:

```bash
php artisan vendor:publish --tag=devia-config
php artisan vendor:publish --tag=devia-assets
```

- **devia-config**: copia `config/devia.php` in `config/devia.php` dell’app (puoi modificarlo).
- **devia-assets**: copia gli script JS in `public/vendor/devia/` (in particolare `devia-client.js`).

Se non pubblichi gli asset, il widget non troverà `devia-client.js`; assicurati che la route che serve la pagina usi l’asset da `public/vendor/devia/` (vedi sotto).

---

## 3. Configurazione ambiente (`.env`)

Nel file `.env` del progetto Laravel aggiungi:

```env
# Obbligatorio: URL del servizio DevIA (es. dove gira il backend FastAPI)
DEVIA_API_URL=http://localhost:8787

# Opzionale: frase da pronunciare per aprire la sessione (default: ehi devia)
DEVIA_VOICE_TRIGGER=ehi devia
```

- In produzione imposta `DEVIA_API_URL` con l’URL reale del servizio DevIA (es. `https://devia.tuodominio.it`).
- `DEVIA_VOICE_TRIGGER` può essere cambiata (es. `ok devia`).

---

## 4. Includere il widget nelle pagine (invisibile)

Il plugin deve essere caricato nelle pagine dove vuoi DevIA (di solito nel layout condiviso).

1. Apri il layout Blade usato per le pagine pubbliche (es. `resources/views/layouts/app.blade.php`).

2. Prima della chiusura di `</body>`, inserisci **una** di queste due righe:

```blade
@devia
```

oppure:

```blade
@include('devia::widget')
```

Salva il file. Il widget è **invisibile**: non occupa spazio e non mostra nulla finché l’utente non dice la frase configurata (es. “ehi DevIa”).

---

## 5. Verifica che gli asset siano raggiungibili

Il widget carica lo script da:

`/vendor/devia/devia-client.js`

cioè da `public/vendor/devia/devia-client.js` dopo il publish. Se la tua app usa un subpath o una CDN, assicurati che `public/vendor/devia/` sia servito correttamente (Laravel di default serve tutto ciò che sta in `public/`).

---

## 6. Riepilogo ordine operazioni

| Step | Cosa fare |
|------|-----------|
| 1 | Aggiungere il repo (GitHub VCS o path locale) e `require` in `composer.json`, poi `composer update devia/plugin-laravel` |
| 2 | `php artisan vendor:publish --tag=devia-config` e `--tag=devia-assets` |
| 3 | Impostare `DEVIA_API_URL` (e opzionale `DEVIA_VOICE_TRIGGER`) in `.env` |
| 4 | Mettere `@devia` (o `@include('devia::widget')`) nel layout, prima di `</body>` |
| 5 | Avviare il servizio DevIA (es. `http://localhost:8787`) e provare la pagina: dire “ehi DevIa” e usare la chat testuale |

---

Con il plugin alla root di questo repo, in Opzione A usi direttamente l’URL di **questo** repo DevIA; non serve un repo dedicato per il plugin.
