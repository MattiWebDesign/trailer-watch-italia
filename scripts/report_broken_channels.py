#!/usr/bin/env python3
"""Apre e chiude le issue di GitHub per i canali che non funzionano.

Legge channel_alerts.json, prodotto da check_trailers.py a ogni scansione:
  - "broken":  canali con problemi da almeno HEALTH_THRESHOLD scansioni di fila;
               per ciascuno si apre una issue, se non ne esiste già una per
               questo stesso periodo di problemi;
  - "healthy": canali che hanno funzionato; se ne hanno una aperta la si chiude
               con un commento.

Variabili d'ambiente (le imposta il workflow):
  GITHUB_TOKEN        token del workflow, serve il permesso `issues: write`
  GITHUB_REPOSITORY   "proprietario/repo"

Se mancano lo script stampa cosa farebbe e termina senza errore, così si può
provare in locale.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALERTS_FILE = ROOT / "channel_alerts.json"

LABEL = "canale-rotto"
LABEL_COLOR = "d93f0b"
TITLE_PREFIX = "Canale non funzionante: "
API = "https://api.github.com"


def api(method, path, token, payload=None):
    """Chiamata all'API REST di GitHub. Restituisce il JSON della risposta."""
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "trailer-watch-italia",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else None


def parse_iso(value):
    """Data ISO di GitHub ("...Z") o di Python ("...+00:00") in datetime."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def issue_body(item):
    handle = item.get("handle", "")
    link = f"https://www.youtube.com/@{handle}" if handle else ""
    return (
        f"Il canale **{item['name']}**"
        + (f" ([@{handle}]({link}))" if handle else "")
        + f" ha dato problemi in **{item['failures']} scansioni consecutive**, "
        f"a partire dal {item.get('since', '?')}.\n\n"
        f"Ultimo problema: {item.get('problem', 'sconosciuto')}\n\n"
        "Cosa controllare:\n"
        "- l'handle in `CHANNELS` (`scripts/check_trailers.py`) esiste ancora e non è stato rinominato;\n"
        "- il canale è ancora attivo e pubblica video;\n"
        "- il log dell'ultima run del workflow *Check trailers* (righe `[WARN]` e `[OK]`).\n\n"
        "La issue si chiude da sola appena il canale torna a funzionare.\n"
    )


def plan(alerts, issues):
    """Decide cosa fare, senza toccare la rete.

    `issues` sono tutte le issue con l'etichetta, aperte e chiuse. Ritorna
    (da_aprire, da_chiudere): lista di canali "broken" e lista di issue aperte
    da chiudere perché il canale è tornato sano.

    Una issue già chiusa a mano non viene riaperta né duplicata finché dura lo
    stesso periodo di problemi (created_at >= since): altrimenti, chiudendola
    senza aver sistemato l'handle, se ne riceverebbe una nuova a ogni scansione.
    """
    da_aprire = []
    for item in alerts.get("broken", []):
        titolo = TITLE_PREFIX + item["name"]
        since = parse_iso(item.get("since"))
        gia = [
            i for i in issues
            if i["title"] == titolo
            and (since is None or (parse_iso(i["created_at"]) or since) >= since)
        ]
        if not gia:
            da_aprire.append(item)

    sani = set(alerts.get("healthy", []))
    da_chiudere = [
        i for i in issues
        if i["state"] == "open" and i["title"].startswith(TITLE_PREFIX)
        and i["title"][len(TITLE_PREFIX):] in sani
    ]
    return da_aprire, da_chiudere


def main():
    if not ALERTS_FILE.exists():
        print("Nessun channel_alerts.json: niente da segnalare.")
        return 0
    alerts = json.loads(ALERTS_FILE.read_text(encoding="utf-8"))

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GITHUB_TOKEN/GITHUB_REPOSITORY mancanti: simulazione senza chiamate.")
        for item in alerts.get("broken", []):
            print(f"  aprirebbe una issue per {item['name']} ({item['failures']} scansioni)")
        return 0

    if not alerts.get("broken") and not alerts.get("healthy"):
        return 0

    issues = api("GET", f"/repos/{repo}/issues?labels={LABEL}&state=all&per_page=100", token) or []
    da_aprire, da_chiudere = plan(alerts, issues)

    if da_aprire:
        try:
            api("POST", f"/repos/{repo}/labels", token, {
                "name": LABEL, "color": LABEL_COLOR,
                "description": "Un canale YouTube monitorato non risponde più",
            })
        except urllib.error.HTTPError as exc:
            if exc.code != 422:   # 422 = l'etichetta esiste già
                raise

    for item in da_aprire:
        created = api("POST", f"/repos/{repo}/issues", token, {
            "title": TITLE_PREFIX + item["name"],
            "body": issue_body(item),
            "labels": [LABEL],
        })
        print(f"Aperta issue #{created['number']} per {item['name']}")

    for issue in da_chiudere:
        api("POST", f"/repos/{repo}/issues/{issue['number']}/comments", token,
            {"body": "Il canale è tornato a rispondere: chiudo la segnalazione."})
        api("PATCH", f"/repos/{repo}/issues/{issue['number']}", token,
            {"state": "closed", "state_reason": "completed"})
        print(f"Chiusa issue #{issue['number']} ({issue['title']})")

    if not da_aprire and not da_chiudere:
        print("Nessuna issue da aprire o chiudere.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as exc:
        # un problema nel segnalare non deve far fallire la run
        print(f"[WARN] impossibile aggiornare le issue: {exc}", file=sys.stderr)
        sys.exit(0)
