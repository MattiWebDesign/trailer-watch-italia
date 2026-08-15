#!/usr/bin/env python3
"""Cerca nuovi trailer sui canali YouTube ufficiali via RSS e aggiorna data.json.

Oltre a data.json/seen_ids.json scrive new_trailers.json (file temporaneo, non
versionato) con i soli trailer trovati in questa esecuzione: lo usa
scripts/notify_telegram.py per mandare le notifiche.
"""
import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data.json"
SEEN_FILE = ROOT / "seen_ids.json"
NEW_FILE = ROOT / "new_trailers.json"

MAX_TRAILERS = 60
KEYWORD_RE = re.compile(r"trailer|teaser", re.IGNORECASE)

# Handle YouTube di ciascun canale. Se un canale smette di funzionare
# (log "impossibile risolvere channel_id"), verificare/correggere l'handle qui.
# aggregator=True per i canali che rilanciano contenuti altrui: a parità di
# trailer vince sempre il canale ufficiale (vedi deduplicazione più sotto).
CHANNELS = [
    # piattaforme streaming
    {"name": "Netflix", "handle": "NetflixItalia"},
    {"name": "Prime Video", "handle": "PrimeVideoIT"},
    {"name": "Disney+", "handle": "DisneyPlusIT"},
    {"name": "Paramount+", "handle": "ParamountPlusIT"},
    {"name": "HBO Max", "handle": "hbomaxit"},
    # distribuzione cinematografica
    {"name": "Warner Bros.", "handle": "WarnerBrosItalia"},
    {"name": "Sony Pictures", "handle": "SonyPicturesIT"},
    {"name": "Paramount Pictures", "handle": "ParamountPicturesItalia"},
    {"name": "Universal Pictures", "handle": "UniversalpicturesIt"},
    {"name": "Marvel", "handle": "MarvelItaly"},
    # aggregatori: pubblicano molti trailer al giorno
    {"name": "FilmIsNow", "handle": "FilmIsNowItalia", "aggregator": True},
    {"name": "Box Office Trailers", "handle": "boxofficetrailersitaly", "aggregator": True},
]

AGGREGATORS = {c["name"] for c in CHANNELS if c.get("aggregator")}

# ---------------------------------------------------------------------------
# Deduplicazione cross-canale
#
# Lo stesso trailer viene spesso pubblicato da più canali (Marvel e Disney+, o
# un aggregatore che rilancia un canale ufficiale): sono video YouTube diversi,
# quindi con id diversi, e il filtro su seen_ids non li intercetta.
#
# Si confrontano i titoli normalizzati: via accenti, punteggiatura, marcatori di
# lingua/qualità e nomi dei canali. Le parole che indicano il TIPO di video
# ("trailer", "teaser", "final", "nuovo"...) restano invece nel confronto,
# perché il teaser e il trailer finale dello stesso film sono video distinti e
# non vanno accorpati.
# ---------------------------------------------------------------------------
DUPLICATE_RATIO = 0.86      # soglia di somiglianza fra titoli normalizzati
DUPLICATE_WINDOW_DAYS = 30  # oltre questa distanza è una ripubblicazione, non un duplicato

MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")

# marcatori senza valore identificativo: lingua, qualità, promozione, brand
NOISE_WORDS = {
    # lingua e qualità
    "ita", "italiano", "italiana", "italiane", "sub", "subita", "subtitles",
    "hd", "fullhd", "4k", "uhd", "1080p", "720p",
    # promozione
    "ufficiale", "ufficiali", "official", "esclusiva", "esclusivo",
    "dal", "dalla", "al", "alla", "su", "in", "cinema", "solo", "adesso", "ora",
    "disponibile", "guarda", "prossimamente",
    # nomi dei canali e dei brand
    "netflix", "prime", "video", "amazon", "disney", "paramount", "plus",
    "hbo", "max", "warner", "bros", "sony", "pictures", "universal",
    "marvel", "studios", "filmisnow", "office", "trailers", "italia", "italy",
    *MESI,
}

# "(2026)" aggiunto dagli aggregatori accanto al titolo: non fa parte del titolo.
# Solo fra parentesi, per non cancellare film che si chiamano davvero "1917".
YEAR_PAREN_RE = re.compile(r"\(\s*(?:19|20)\d{2}\s*\)")
# date di uscita tipo "dal 25 dicembre al cinema"
DATE_RE = re.compile(r"\b\d{1,2}\s+(?:" + "|".join(MESI) + r")\b")

# numeri scritti a parole: senza questi "Chapter One" e "Chapter Two"
# risulterebbero lo stesso trailer
NUMBER_WORDS = {
    "uno": 1, "one": 1, "primo": 1, "prima": 1, "first": 1,
    "due": 2, "two": 2, "secondo": 2, "seconda": 2, "second": 2,
    "tre": 3, "three": 3, "terzo": 3, "terza": 3, "third": 3,
    "quattro": 4, "four": 4, "quarto": 4, "quarta": 4, "fourth": 4,
    "cinque": 5, "five": 5, "quinto": 5, "quinta": 5, "fifth": 5,
    "sei": 6, "six": 6, "sesto": 6, "sesta": 6, "sixth": 6,
    "sette": 7, "seven": 7, "settimo": 7, "settima": 7, "seventh": 7,
    "otto": 8, "eight": 8, "ottavo": 8, "ottava": 8, "eighth": 8,
    "nove": 9, "nine": 9, "nono": 9, "nona": 9, "ninth": 9,
    "dieci": 10, "ten": 10, "decimo": 10, "decima": 10, "tenth": 10,
}


def normalize_title(title):
    """Riduce un titolo alla sua parte identificativa, per il confronto."""
    text = YEAR_PAREN_RE.sub(" ", str(title or "").lower())
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = DATE_RE.sub(" ", text)
    words = [w for w in text.split() if w not in NOISE_WORDS]
    return " ".join(words)


def parse_published(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def identity_numbers(key):
    """Numeri che identificano il contenuto: stagioni e sequel, non gli anni.

    Senza questo controllo "Avatar 3" e "Avatar 4" risulterebbero lo stesso
    trailer: differiscono per un solo carattere su un titolo lungo, quindi la
    somiglianza resta sopra soglia. Gli anni vanno invece ignorati, perché un
    canale scrive "(2026)" nel titolo e l'altro no.
    """
    numeri = [int(n) for n in re.findall(r"\d+", key) if not 1900 <= int(n) <= 2100]
    numeri += [NUMBER_WORDS[w] for w in key.split() if w in NUMBER_WORDS]
    return sorted(numeri)


def similarity(key_a, key_b):
    """Somiglianza fra due titoli normalizzati, indipendente dall'ordine.

    Gli aggregatori riordinano spesso i pezzi del titolo ("Verity | Trailer |
    Dal 1 ottobre" contro "Verity | Dal 1 ottobre | Trailer"), quindi al
    confronto diretto si affianca quello sulle parole ordinate alfabeticamente.
    """
    diretta = SequenceMatcher(None, key_a, key_b).ratio()
    ordinata = SequenceMatcher(
        None, " ".join(sorted(key_a.split())), " ".join(sorted(key_b.split()))
    ).ratio()
    return max(diretta, ordinata)


def same_trailer(a, b):
    """True se i due elementi sono ragionevolmente lo stesso trailer."""
    key_a, key_b = a.get("_key", ""), b.get("_key", "")
    if not key_a or not key_b:
        return False

    date_a, date_b = parse_published(a.get("published")), parse_published(b.get("published"))
    if date_a and date_b and abs(date_a - date_b) > timedelta(days=DUPLICATE_WINDOW_DAYS):
        return False

    if identity_numbers(key_a) != identity_numbers(key_b):
        return False

    if key_a == key_b:
        return True
    return similarity(key_a, key_b) >= DUPLICATE_RATIO


def _priority(trailer):
    """Ordine di preferenza a parità di trailer: prima i canali ufficiali."""
    is_aggregator = trailer.get("channel") in AGGREGATORS
    published = parse_published(trailer.get("published"))
    # a parità di tipo di canale vince chi ha pubblicato per primo (l'originale)
    return (1 if is_aggregator else 0, published or datetime.max.replace(tzinfo=timezone.utc))


def dedupe_cross_channel(trailers):
    """Tiene un solo elemento per trailer, annotando su quali altri canali è uscito.

    Restituisce (kept, absorbed): il secondo è la mappa id_vincitore →
    id soppressi, che serve a non rinotificare un trailer già annunciato quando
    lo stesso contenuto ricompare più tardi su un canale con priorità migliore.
    """
    kept = []
    absorbed = {}
    for trailer in trailers:
        trailer["_key"] = normalize_title(trailer.get("title"))
        match = next((k for k in kept if same_trailer(trailer, k)), None)
        if match is None:
            kept.append(trailer)
            continue

        # duplicato: si tiene quello con priorità migliore, l'altro diventa "also_on"
        winner, loser = (trailer, match) if _priority(trailer) < _priority(match) else (match, trailer)
        if winner is not match:
            kept[kept.index(match)] = winner

        also_on = list(dict.fromkeys(
            match.get("also_on", []) + trailer.get("also_on", []) + [loser.get("channel")]
        ))
        winner["also_on"] = [c for c in also_on if c and c != winner.get("channel")]

        # gli id già assorbiti dal perdente passano al vincitore
        ereditati = absorbed.pop(loser["id"], []) + absorbed.pop(winner["id"], [])
        absorbed[winner["id"]] = list(dict.fromkeys(ereditati + [loser["id"]]))

        print(f"[DEDUP] «{loser.get('title')}» ({loser.get('channel')}) "
              f"→ già presente come «{winner.get('title')}» ({winner.get('channel')})")

    for trailer in kept:
        trailer.pop("_key", None)
    return kept, absorbed

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cookie": "CONSENT=YES+1",
}

CHANNEL_ID_RE = re.compile(r"channel_id=(UC[0-9A-Za-z_-]{22})")
ATOM_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def resolve_channel_id(handle):
    html = fetch(f"https://www.youtube.com/@{handle}")
    match = CHANNEL_ID_RE.search(html)
    if not match:
        raise ValueError(f"channel_id non trovato per @{handle}")
    return match.group(1)


def fetch_feed_entries(channel_id):
    xml_text = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    root = ElementTree.fromstring(xml_text)
    entries = []
    for entry in root.findall("a:entry", ATOM_NS):
        video_id = entry.findtext("yt:videoId", default="", namespaces=ATOM_NS)
        title = entry.findtext("a:title", default="", namespaces=ATOM_NS)
        published = entry.findtext("a:published", default="", namespaces=ATOM_NS)
        if video_id and title:
            entries.append({"id": video_id, "title": title, "published": published})
    return entries


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def main():
    seen_ids = set(load_json(SEEN_FILE, []))
    data = load_json(DATA_FILE, {"updated_at": None, "trailers": []})
    existing_trailers = data.get("trailers", [])

    new_trailers = []
    had_error = False

    for channel in CHANNELS:
        name, handle = channel["name"], channel["handle"]
        try:
            channel_id = resolve_channel_id(handle)
            entries = fetch_feed_entries(channel_id)
        except Exception as exc:  # rete/parsing: non bloccare gli altri canali
            print(f"[WARN] {name} (@{handle}): {exc}", file=sys.stderr)
            had_error = True
            continue

        found = 0
        for entry in entries:
            if entry["id"] in seen_ids:
                continue
            if not KEYWORD_RE.search(entry["title"]):
                continue
            seen_ids.add(entry["id"])
            new_trailers.append({
                "id": entry["id"],
                "title": entry["title"],
                "channel": name,
                "published": entry["published"],
                "url": f"https://www.youtube.com/watch?v={entry['id']}",
            })
            found += 1
        print(f"[OK] {name} (@{handle}): {found} nuovi trailer")

    # dedup per id video, mantenendo la prima occorrenza (i nuovi hanno priorità)
    dedup = {}
    for t in new_trailers + existing_trailers:
        dedup.setdefault(t["id"], t)
    ordered = sorted(dedup.values(), key=lambda t: t.get("published", ""), reverse=True)

    # dedup per contenuto: lo stesso trailer uscito su più canali resta uno solo
    deduped, absorbed = dedupe_cross_channel(ordered)
    merged = deduped[:MAX_TRAILERS]

    data["trailers"] = merged
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SEEN_FILE.write_text(json.dumps(sorted(seen_ids), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Notifiche solo per i nuovi trailer sopravvissuti alla deduplicazione: senza
    # questo filtro un trailer rilanciato da un aggregatore genererebbe un secondo
    # messaggio Telegram identico al primo.
    kept_ids = {t["id"] for t in merged}
    existing_ids = {t["id"] for t in existing_trailers}

    def gia_annunciato(trailer):
        """Vero se questo trailer ha soppiantato un video già presente in data.json.

        Capita quando un aggregatore pubblica prima del canale ufficiale: il
        contenuto era già stato notificato con l'altro video, quindi il vincitore
        aggiorna l'elenco ma non fa partire un secondo messaggio.
        """
        return any(vid in existing_ids for vid in absorbed.get(trailer["id"], []))

    notify_list = sorted(
        (t for t in new_trailers if t["id"] in kept_ids and not gia_annunciato(t)),
        key=lambda t: t.get("published", ""),
        reverse=True,
    )
    NEW_FILE.write_text(json.dumps(notify_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    soppressi = len(new_trailers) - len(notify_list)
    print(f"Totale nuovi trailer trovati: {len(new_trailers)}"
          + (f" ({soppressi} duplicati di altri canali, non notificati)" if soppressi else ""))

    # espone il conteggio agli step successivi del workflow GitHub Actions:
    # è quello dei trailer da notificare, così se sono tutti duplicati lo step
    # delle notifiche viene saltato invece di girare a vuoto
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"new_count={len(notify_list)}\n")

    if had_error and not new_trailers:
        # nessun risultato ma almeno un canale ha fallito: segnalarlo nei log
        # senza far fallire la run (gli altri canali potrebbero aver funzionato)
        pass


if __name__ == "__main__":
    main()
