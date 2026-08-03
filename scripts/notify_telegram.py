#!/usr/bin/env python3
"""Invia su Telegram i nuovi trailer trovati da check_trailers.py.

Uso:
  python scripts/notify_telegram.py            invia i trailer di new_trailers.json
  python scripts/notify_telegram.py --test     invia una notifica di prova

Variabili d'ambiente (impostate come GitHub Secrets nel workflow):
  TELEGRAM_BOT_TOKEN   token del bot ottenuto da @BotFather            (obbligatorio)
  TELEGRAM_CHAT_ID     id del canale/gruppo/chat di destinazione       (obbligatorio)
  TELEGRAM_SILENT      "1" per inviare senza suono di notifica         (opzionale)

Se i due valori obbligatori mancano lo script esce senza errore: in questo modo
un fork o una run senza secret configurati non fallisce. In modalità --test,
invece, la configurazione mancante è un errore: il test è stato chiesto apposta.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEW_FILE = ROOT / "new_trailers.json"
DATA_FILE = ROOT / "data.json"

API = "https://api.telegram.org/bot{token}/sendMessage"
API_ME = "https://api.telegram.org/bot{token}/getMe"
MAX_MESSAGES = 8          # oltre questa soglia manda un riepilogo unico
DELAY_SECONDS = 1.2       # margine sui limiti di frequenza di Telegram

MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def esc(text):
    """Escape per il parse_mode HTML di Telegram."""
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def fmt_date(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    return f"{d.day} {MESI[d.month - 1]} {d.year}"


def send(token, chat_id, text, silent=False, preview=True):
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false" if preview else "true",
        "disable_notification": "true" if silent else "false",
    }).encode("utf-8")

    req = urllib.request.Request(API.format(token=token), data=payload)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not body.get("ok"):
        raise RuntimeError(f"risposta Telegram non ok: {body}")
    return body


def describe_error(exc):
    """Messaggi leggibili per gli errori più comuni di configurazione."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = json.loads(exc.read().decode("utf-8", errors="replace"))
            desc = detail.get("description", "")
        except Exception:
            desc = ""
        if exc.code == 401:
            return "token del bot non valido (controlla TELEGRAM_BOT_TOKEN)"
        if exc.code == 400 and "chat not found" in desc.lower():
            return "chat non trovata: verifica TELEGRAM_CHAT_ID e che il bot sia stato aggiunto alla chat"
        if exc.code == 403:
            return "il bot non ha il permesso di scrivere in questa chat (aggiungilo come amministratore)"
        return f"HTTP {exc.code}: {desc or exc.reason}"
    return str(exc)


def trailer_message(t):
    """Il messaggio esattamente com'è quando esce un trailer nuovo."""
    return (
        f"🎬 <b>{esc(t.get('title'))}</b>\n"
        f"📺 {esc(t.get('channel'))}"
        + (f" · {esc(fmt_date(t.get('published')))}" if t.get("published") else "")
        + f"\n\n{esc(t.get('url'))}"
    )


def run_test(token, chat_id, silent):
    """Notifica di prova: conferma che token, chat id e permessi sono corretti."""
    try:
        req = urllib.request.Request(API_ME.format(token=token))
        with urllib.request.urlopen(req, timeout=20) as resp:
            me = json.loads(resp.read().decode("utf-8", errors="replace"))
        username = me.get("result", {}).get("username", "?")
        print(f"[OK] Bot autenticato: @{username}")
    except Exception as exc:
        print(f"[ERRORE] autenticazione del bot fallita: {describe_error(exc)}", file=sys.stderr)
        return 1

    testo = (
        "🧪 <b>Notifica di prova</b>\n"
        "Trailer Watch Italia è collegato correttamente a questa chat.\n\n"
        "Da qui in poi riceverai un messaggio a ogni nuovo trailer trovato."
    )
    try:
        send(token, chat_id, testo, silent=silent, preview=False)
        print(f"[OK] Messaggio di prova inviato alla chat {chat_id}.")
    except Exception as exc:
        print(f"[ERRORE] invio del messaggio di prova fallito: {describe_error(exc)}", file=sys.stderr)
        return 1

    # secondo messaggio: un esempio reale, così si vede il formato definitivo
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        esempio = (data.get("trailers") or [])[0]
    except (json.JSONDecodeError, OSError, IndexError):
        esempio = None

    if esempio:
        time.sleep(DELAY_SECONDS)
        try:
            send(token, chat_id, trailer_message(esempio), silent=silent)
            print("[OK] Inviato anche un esempio di notifica con un trailer reale.")
        except Exception as exc:
            print(f"[ERRORE] invio dell'esempio fallito: {describe_error(exc)}", file=sys.stderr)
            return 1

    return 0


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    silent = os.environ.get("TELEGRAM_SILENT", "").strip() == "1"
    test_mode = "--test" in sys.argv[1:]

    if not token or not chat_id:
        if test_mode:
            # il test è stato richiesto esplicitamente: la configurazione mancante è un errore
            mancanti = [
                n for n, v in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat_id)) if not v
            ]
            accordo = "non configurati" if len(mancanti) > 1 else "non configurato"
            print(
                f"[ERRORE] {' e '.join(mancanti)} {accordo}: impossibile inviare il test.",
                file=sys.stderr,
            )
            return 1
        print("[SKIP] TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID non configurati: notifiche disattivate.")
        return 0

    if test_mode:
        return run_test(token, chat_id, silent)

    if not NEW_FILE.exists():
        print("[SKIP] new_trailers.json non trovato: nessuna notifica da inviare.")
        return 0

    try:
        trailers = json.loads(NEW_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[ERRORE] impossibile leggere new_trailers.json: {exc}", file=sys.stderr)
        return 1

    if not trailers:
        print("[OK] Nessun nuovo trailer: niente da notificare.")
        return 0

    failures = 0

    if len(trailers) > MAX_MESSAGES:
        # troppi risultati (es. primo avvio): un solo messaggio di riepilogo
        righe = [f"🎬 <b>{len(trailers)} nuovi trailer</b> disponibili\n"]
        for t in trailers[:20]:
            righe.append(
                f"• <a href=\"{esc(t.get('url'))}\">{esc(t.get('title'))}</a> "
                f"<i>({esc(t.get('channel'))})</i>"
            )
        if len(trailers) > 20:
            righe.append(f"\n…e altri {len(trailers) - 20}.")
        try:
            send(token, chat_id, "\n".join(righe), silent=silent, preview=False)
            print(f"[OK] Inviato riepilogo con {len(trailers)} trailer.")
        except Exception as exc:
            print(f"[ERRORE] invio riepilogo fallito: {describe_error(exc)}", file=sys.stderr)
            failures += 1
    else:
        for i, t in enumerate(trailers):
            try:
                send(token, chat_id, trailer_message(t), silent=silent)
                print(f"[OK] Notificato: {t.get('title')}")
            except Exception as exc:
                print(f"[ERRORE] invio fallito per {t.get('id')}: {describe_error(exc)}", file=sys.stderr)
                failures += 1
            if i < len(trailers) - 1:
                time.sleep(DELAY_SECONDS)

    if failures:
        print(f"[ERRORE] {failures} notifiche non inviate.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
