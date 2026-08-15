# Trailer Watch Italia

Aggregatore automatico di trailer e teaser **in italiano** dai canali YouTube ufficiali
delle principali piattaforme streaming. Nessun backend e nessun database: solo file
statici nel repository, aggiornati ogni giorno da GitHub Actions.

## Come funziona

1. Ogni giorno alle **06:00 UTC** (o su avvio manuale) parte il workflow
   `.github/workflows/check-trailers.yml`.
2. `scripts/check_trailers.py` legge i feed RSS pubblici di YouTube di ogni canale,
   tiene i video con "trailer" o "teaser" nel titolo e scarta quelli già visti.
3. Vengono aggiornati `data.json` (fino a 60 trailer, dal più recente) e
   `seen_ids.json` (memoria anti-duplicati), poi committati automaticamente.
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
| `.github/workflows/check-trailers.yml` | Pianificazione giornaliera, commit automatico e notifiche |
| `robots.txt` | Blocca l'indicizzazione da parte dei motori di ricerca |

`new_trailers.json` viene creato a ogni esecuzione con i soli trailer nuovi e serve
solo alle notifiche: è in `.gitignore` e non viene versionato.

## Funzioni del sito

- Ricerca testuale immediata su titolo e piattaforma
- Filtri per piattaforma con conteggi
- Stato condivisibile nell'URL: `?q=dune&canale=netflix&vista=lista`
- Vista griglia o elenco compatto
- Player YouTube in finestra modale, senza uscire dal sito
- Contatore live dall'ultimo controllo e conto alla rovescia al prossimo
- Etichetta "Nuovo" sui trailer usciti nelle ultime 72 ore
- Segna i trailer come visti (icona sulla card o selezione multipla) — restano
  visibili con il badge "Visto", oppure eliminali dall'elenco; stato salvato nel
  browser (`localStorage`), personale per dispositivo e non sincronizzato
- Pulsante "Scansiona ora" in alto: apre la pagina Actions di GitHub per avviare
  un controllo manuale senza aspettare le 06:00 UTC
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

`FilmIsNow` e `Box Office Trailers` sono aggregatori, non canali ufficiali: pubblicano
parecchi video al giorno, quindi peseranno sui risultati più degli altri. Per toglierli
basta rimuovere le rispettive righe da `CHANNELS`.

## Deduplicazione fra canali

Lo stesso trailer esce spesso su più canali (Marvel e Disney+, o un aggregatore che
rilancia un canale ufficiale): sono video YouTube distinti, con id diversi, quindi il
filtro su `seen_ids.json` non li intercetta. Lo scraper li riconosce confrontando i
titoli normalizzati e ne tiene uno solo, dando la precedenza al canale ufficiale; gli
altri finiscono nel campo `also_on` del trailer e non generano una seconda notifica.

Cosa viene ignorato nel confronto: accenti e punteggiatura, marcatori di lingua e
qualità (`ITA`, `HD`, `4K`), formule promozionali e date di uscita (`Dal 25 dicembre al
cinema`), l'anno fra parentesi che aggiungono gli aggregatori (`(2026)`) e i nomi dei
canali.

Cosa invece **non** viene accorpato:

- teaser e trailer finale dello stesso film, perché le parole che indicano il tipo di
  video restano nel confronto;
- stagioni e sequel diversi, anche scritti a parole: `Chapter One` e `Chapter Two`, o
  `Avatar 3` e `Avatar 4`, differiscono per pochi caratteri ma non vanno uniti;
- ripubblicazioni a distanza di oltre 30 giorni, che sono lanci diversi e non copie.

Le soglie sono in cima a `scripts/check_trailers.py` (`DUPLICATE_RATIO`,
`DUPLICATE_WINDOW_DAYS`) e ogni accorpamento viene scritto nel log della run con la
riga `[DEDUP]`, per accorgersi subito di eventuali unioni sbagliate.

## Aggiungere una piattaforma

In `scripts/check_trailers.py`, aggiungi una voce alla lista `CHANNELS` con il nome da
mostrare e l'handle YouTube del canale:

```python
{"name": "Apple TV+", "handle": "AppleTVIT"},
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
