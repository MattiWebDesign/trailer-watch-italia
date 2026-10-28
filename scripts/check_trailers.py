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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data.json"
SEEN_FILE = ROOT / "seen_ids.json"
NEW_FILE = ROOT / "new_trailers.json"
HEALTH_FILE = ROOT / "channel_health.json"
ALERTS_FILE = ROOT / "channel_alerts.json"

MAX_TRAILERS = 60
# scansioni consecutive in cui un canale deve dare problemi prima di segnalarlo:
# un singolo errore di rete di YouTube è normale, tre di fila (18 ore) no
HEALTH_THRESHOLD = 3
KEYWORD_RE = re.compile(r"trailer|teaser", re.IGNORECASE)

# Handle YouTube di ciascun canale. Se un canale smette di funzionare
# (log "impossibile risolvere channel_id"), verificare/correggere l'handle qui.
CHANNELS = [
    # piattaforme streaming
    {"name": "Netflix", "handle": "NetflixItalia"},
    {"name": "Prime Video", "handle": "PrimeVideoIT"},
    {"name": "Disney+", "handle": "DisneyPlusIT"},
    {"name": "Paramount+", "handle": "ParamountPlusIT"},
    {"name": "HBO Max", "handle": "hbomaxit"},
    # canale internazionale: pubblica anche titoli non doppiati in italiano
    {"name": "Apple TV+", "handle": "AppleTV"},
    # distribuzione cinematografica
    {"name": "Warner Bros.", "handle": "WarnerBrosItalia"},
    {"name": "Sony Pictures", "handle": "SonyPicturesIT"},
    {"name": "Paramount Pictures", "handle": "ParamountPicturesItalia"},
    {"name": "Universal Pictures", "handle": "UniversalpicturesIt"},
    {"name": "Marvel", "handle": "MarvelItaly"},
    # aggregatori: pubblicano molti trailer al giorno
    {"name": "FilmIsNow", "handle": "FilmIsNowItalia"},
    {"name": "Box Office Trailers", "handle": "boxofficetrailersitaly"},
]

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


def update_channel_health(health, problems, channel_names, now_iso):
    """Aggiorna il contatore di scansioni consecutive con problemi, canale per canale.

    `problems` mappa il nome del canale al motivo del problema nella scansione
    appena fatta; i canali assenti hanno funzionato. In `health` restano solo i
    canali in difficoltà, così per la maggior parte del tempo il file è `{}` e
    non produce commit.

    Se tutti i canali falliscono insieme il problema è quasi certamente la rete
    del runner o un blocco temporaneo di YouTube, non un handle sbagliato: in
    quel caso lo stato precedente resta com'è e non si segnala nulla.

    Restituisce (health, alerts). `alerts` contiene i canali sopra soglia
    ("broken") e quelli che stanno funzionando ("healthy"): serve a
    scripts/report_broken_channels.py per aprire e chiudere le issue.
    """
    if channel_names and len(problems) >= len(channel_names):
        print("[WARN] tutti i canali hanno dato problemi: probabile errore di rete, "
              "stato di salute dei canali lasciato invariato")
        broken = [dict(name=n, **h) for n, h in health.items() if h.get("failures", 0) >= HEALTH_THRESHOLD]
        return health, {"broken": broken, "healthy": []}

    updated = {}
    for name in channel_names:
        if name in problems:
            before = health.get(name, {})
            updated[name] = {
                "failures": int(before.get("failures", 0)) + 1,
                "since": before.get("since") or now_iso,
                "problem": problems[name],
            }
    broken = [dict(name=n, **h) for n, h in updated.items() if h["failures"] >= HEALTH_THRESHOLD]
    healthy = [n for n in channel_names if n not in problems]
    return updated, {"broken": broken, "healthy": healthy}


def main():
    seen_ids = set(load_json(SEEN_FILE, []))
    data = load_json(DATA_FILE, {"updated_at": None, "trailers": []})
    existing_trailers = data.get("trailers", [])

    new_trailers = []
    had_error = False
    problems = {}   # canale -> motivo, per chi non ha funzionato in questa scansione

    for channel in CHANNELS:
        name, handle = channel["name"], channel["handle"]
        try:
            channel_id = resolve_channel_id(handle)
            entries = fetch_feed_entries(channel_id)
        except Exception as exc:  # rete/parsing: non bloccare gli altri canali
            print(f"[WARN] {name} (@{handle}): {exc}", file=sys.stderr)
            had_error = True
            problems[name] = f"errore: {exc}"
            continue

        if not entries:
            problems[name] = "il feed non contiene nessun video"

        found = 0
        con_keyword = 0
        for entry in entries:
            if not KEYWORD_RE.search(entry["title"]):
                continue
            con_keyword += 1
            if entry["id"] in seen_ids:
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

        # Il dettaglio serve a distinguere i tre motivi per cui un canale può
        # non produrre nulla: feed vuoto, nessun titolo con le parole chiave,
        # oppure video già raccolti in una run precedente.
        print(f"[OK] {name} (@{handle}): {found} nuovi trailer "
              f"({len(entries)} video nel feed, {con_keyword} con trailer/teaser nel titolo)")
        if entries and not con_keyword:
            esempi = " | ".join(e["title"][:60] for e in entries[:3])
            print(f"       nessun titolo contiene \"trailer\" o \"teaser\". Ultimi video: {esempi}")

    # dedup per id video, mantenendo la prima occorrenza (i nuovi hanno priorità)
    dedup = {}
    for t in new_trailers + existing_trailers:
        dedup.setdefault(t["id"], t)
    ordered = sorted(dedup.values(), key=lambda t: t.get("published", ""), reverse=True)
    merged = ordered[:MAX_TRAILERS]

    data["trailers"] = merged
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SEEN_FILE.write_text(json.dumps(sorted(seen_ids), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Notifiche per i nuovi trailer che sono rimasti nell'elenco.
    kept_ids = {t["id"] for t in merged}
    notify_list = sorted(
        (t for t in new_trailers if t["id"] in kept_ids),
        key=lambda t: t.get("published", ""),
        reverse=True,
    )
    NEW_FILE.write_text(json.dumps(notify_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Totale nuovi trailer trovati: {len(new_trailers)}")

    health, alerts = update_channel_health(
        load_json(HEALTH_FILE, {}), problems,
        [c["name"] for c in CHANNELS], data["updated_at"],
    )
    HEALTH_FILE.write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    handles = {c["name"]: c["handle"] for c in CHANNELS}
    for item in alerts["broken"]:
        item["handle"] = handles.get(item["name"], "")
    ALERTS_FILE.write_text(json.dumps(alerts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in alerts["broken"]:
        print(f"[ALERT] {item['name']}: {item['failures']} scansioni di fila con problemi ({item['problem']})")

    # espone il conteggio agli step successivi del workflow GitHub Actions:
    # se è zero lo step delle notifiche viene saltato invece di girare a vuoto
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
