#!/usr/bin/env python3
"""Invia su Telegram i nuovi trailer trovati da check_trailers.py.

Variabili d'ambiente (impostate come GitHub Secrets nel workflow):
  TELEGRAM_BOT_TOKEN   token del bot ottenuto da @BotFather            (obbligatorio)
  TELEGRAM_CHAT_ID     id del canale/gruppo/chat di destinazione       (obbligatorio)
  TELEGRAM_SILENT      "1" per inviare senza suono di notifica         (opzionale)

Se i due valori obbligatori mancano lo script esce senza errore: in questo modo
un fork o una run senza secret configurati non fallisce.
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

API = "https://api.telegram.org/bot{token}/sendMessage"
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


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    silent = os.environ.get("TELEGRAM_SILENT", "").strip() == "1"

    if not token or not chat_id:
        print("[SKIP] TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID non configurati: notifiche disattivate.")
        return 0

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
            testo = (
                f"🎬 <b>{esc(t.get('title'))}</b>\n"
                f"📺 {esc(t.get('channel'))}"
                + (f" · {esc(fmt_date(t.get('published')))}" if t.get("published") else "")
                + f"\n\n{esc(t.get('url'))}"
            )
            try:
                send(token, chat_id, testo, silent=silent)
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
