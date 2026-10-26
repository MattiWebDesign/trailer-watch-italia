# Trailer Watch Italia

Aggregatore automatico di trailer e teaser **in italiano** dai canali YouTube di
piattaforme streaming, case di distribuzione e aggregatori. Nessun backend e nessun
database: solo file statici nel repository, aggiornati ogni sei ore da GitHub Actions.

## Come funziona

1. **Ogni sei ore** (00:17, 06:17, 12:17 e 18:17 UTC, o su avvio manuale) parte il
   workflow `.github/workflows/check-trailers.yml`. Il minuto è sfalsato perché le run
   pianificate al minuto 0 sono le più soggette a ritardi sui runner di GitHub.
2. `scripts/check_trailers.py` legge i feed RSS pubblici di YouTube di ogni canale,
   tiene i video con "trailer" o "teaser" nel titolo e scarta quelli già visti.
3. Vengono aggiornati `data.json` (fino a 60 trailer, dal più recente) e
   `seen_ids.json` (id già elaborati), poi committati automaticamente.
4. `scripts/notify_telegram.py` manda i nuovi trailer su Telegram, se configurato.
5. `index.html` legge `data.json` lato browser e mostra la galleria.

## Struttura

| Percorso | Funzione |
|---|---|
| `index.html` | Tutto il front-end: HTML, CSS e JS in un unico file, senza dipendenze né build |
| `data.json` | Elenco dei trailer mostrati dal sito |
| `seen_ids.json` | ID YouTube già elaborati, per non riproporre gli stessi video |
| `assets/` | Favicon, icona iOS e immagine di anteprima per le condivisioni |
| `scripts/check_trailers.py` | Lo scraper dei feed YouTube |
| `scripts/notify_telegram.py` | Invio delle notifiche Telegram |
| `.github/workflows/check-trailers.yml` | Pianificazione ogni sei ore, commit automatico e notifiche |
| `robots.txt` | Blocca l'indicizzazione da parte dei motori di ricerca |

`new_trailers.json` viene creato a ogni esecuzione con i soli trailer nuovi e serve
solo alle notifiche: è in `.gitignore` e non viene versionato.

## Funzioni del sito

- Ricerca testuale immediata su titolo e piattaforma
- Filtri per piattaforma con conteggi
- Stato condivisibile nell'URL: `?q=dune&canale=netflix&vista=lista`
- Vista griglia o elenco compatto
- Paginazione a 20 card per pagina (`PAGE_SIZE` in `index.html`), con pagina
  corrente nell'URL: `?pagina=2`
- Player YouTube in finestra modale, senza uscire dal sito
- Contatore live dall'ultimo controllo e conto alla rovescia al prossimo
- Etichetta "Nuovo" sui trailer usciti nelle ultime 72 ore
- Segna i trailer come visti dall'icona sulla card, dalla selezione multipla o dal
  pulsante "Segna visto e chiudi" in fondo al player. I già visti restano in elenco
  ma arretrano: miniatura in bianco e nero e sfocata, titolo e metadati attenuati,
  etichetta "Visto". Passando il mouse tornano nitidi e leggibili
- In alternativa puoi eliminare i trailer dall'elenco; l'operazione è reversibile dal
  link "Ripristina eliminati"
- Lo stato "visto"/"eliminato" è salvato nel browser (`localStorage`): è personale per
  dispositivo e non si sincronizza fra telefono e computer
- Segnare un trailer aggiorna solo la sua card, senza ridisegnare la pagina
- Pulsante "Scansiona ora" in alto: apre la pagina Actions di GitHub per avviare
  un controllo manuale senza aspettare la scansione successiva
- Scorciatoie da tastiera: `/` per cercare, `Esc` per chiudere il player o uscire
  dalla selezione multipla

## Canali monitorati

| Piattaforme streaming | Case di distribuzione | Aggregatori |
|---|---|---|
| Netflix `@NetflixItalia` | Warner Bros. `@WarnerBrosItalia` | FilmIsNow `@FilmIsNowItalia` |
| Prime Video `@PrimeVideoIT` | Sony Pictures `@SonyPicturesIT` | Box Office Trailers `@boxofficetrailersitaly` |
| Disney+ `@DisneyPlusIT` | Paramount Pictures `@ParamountPicturesItalia` | |
| Paramount+ `@ParamountPlusIT` | Universal Pictures `@UniversalpicturesIt` | |
| HBO Max `@hbomaxit` | Marvel `@MarvelItaly` | |
| Apple TV+ `@AppleTV` | | |

`Apple TV+` è l'unico canale internazionale della lista: non esiste un equivalente
italiano, quindi pubblica anche trailer non doppiati. Se i titoli in inglese danno
fastidio, basta rimuovere la sua riga da `CHANNELS`.

`FilmIsNow` e `Box Office Trailers` sono aggregatori, non canali ufficiali: pubblicano
parecchi video al giorno, quindi peseranno sui risultati più degli altri. Per toglierli
basta rimuovere le rispettive righe da `CHANNELS`.

Lo stesso trailer può comparire più volte se esce su più canali (per esempio Marvel e
Disney+, o un aggregatore che lo rilancia): sono video YouTube distinti e il sito li
mostra tutti, senza tentare di accorparli.

## Leggere il log di una run

Ogni canale stampa una riga che dice non solo quanti trailer nuovi ha prodotto, ma
anche quanti video c'erano nel feed e quanti avevano le parole chiave nel titolo:

```
[OK] Netflix (@NetflixItalia): 2 nuovi trailer (15 video nel feed, 3 con trailer/teaser nel titolo)
```

Serve a distinguere i tre motivi per cui un canale può non produrre nulla, che
altrimenti sarebbero indistinguibili:

| Riga | Significato |
|---|---|
| `0 video nel feed` | Il canale non ha pubblicazioni recenti, o l'handle punta altrove |
| `N video nel feed, 0 con trailer/teaser` | Pubblica solo clip, Shorts o contenuti social. Vengono stampati i titoli degli ultimi tre video per vedere come li nomina |
| `N video nel feed, M con trailer/teaser` ma `0 nuovi` | Erano già stati raccolti in una run precedente |
| `[WARN] <nome> (@handle): ...` | Handle non risolvibile o errore di rete: gli altri canali proseguono e la run non fallisce |

Il feed RSS di YouTube restituisce **solo gli ultimi 15 video** di ogni canale: su un
canale che pubblica molti Shorts un trailer può uscire dalla finestra prima di essere
visto. È il motivo per cui la scansione gira ogni sei ore invece di una volta al
giorno: riduce di quattro volte la finestra in cui un trailer può sfuggire.

L'intervallo è definito dal `cron` nel workflow. Se lo cambi, aggiorna anche
`SCAN_EVERY_HOURS` e `SCAN_MINUTE_UTC` in `index.html`, che alimentano il conto alla
rovescia "Prossimo controllo" mostrato dal sito.

## Aggiungere una piattaforma

In `scripts/check_trailers.py`, aggiungi una voce alla lista `CHANNELS` con il nome da
mostrare e l'handle YouTube del canale:

```python
{"name": "Rai Play", "handle": "RaiPlay"},
```

Facoltativo: in `index.html`, aggiungi il colore della piattaforma in `CHANNEL_COLORS`.

## Notifiche Telegram

Le notifiche sono opzionali: senza i secret configurati il workflow salta lo step
senza fallire.

1. Su Telegram apri [@BotFather](https://t.me/BotFather), invia `/newbot` e segui le
   istruzioni. Al termine ricevi il **token** (formato `123456789:AA...`).
2. Crea il canale o il gruppo di destinazione e **aggiungi il bot come amministratore**
   (in un canale serve il permesso di pubblicare messaggi).
3. Recupera il **chat id**:
   - manda un messaggio qualsiasi nella chat, poi apri
     `https://api.telegram.org/bot<TOKEN>/getUpdates` e leggi `chat.id`;
   - i canali e i supergruppi hanno un id negativo, tipo `-1001234567890`.
4. Nel repository vai su **Settings → Secrets and variables → Actions → New repository
   secret** e crea:
   - `TELEGRAM_BOT_TOKEN` → il token del punto 1
   - `TELEGRAM_CHAT_ID` → l'id del punto 3
5. Facoltativo, nella scheda **Variables**: `TELEGRAM_SILENT` = `1` per inviare i
   messaggi senza suono di notifica.

### Notifica di prova

Per verificare la configurazione: **Actions → Check trailers → Run workflow**, spunta
**"Invia una notifica di prova su Telegram"** e avvia. Riceverai due messaggi: la
conferma del collegamento e un esempio con il formato reale di una notifica.

Se qualcosa non va, il log dello step lo dice in chiaro (token non valido, chat non
trovata, bot senza permesso di scrivere).

## Sviluppo locale

```bash
python3 scripts/check_trailers.py   # aggiorna data.json e seen_ids.json
python3 -m http.server 8000         # poi apri http://localhost:8000
```
