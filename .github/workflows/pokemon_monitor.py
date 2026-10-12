
import os
import json
import hashlib
import asyncio
from pathlib import Path
from datetime import datetime, timezone

import aiohttp

# ==========================================================
# KONFIGURATION
# ==========================================================

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

CHECK_INTERVAL_SECONDS = 600  # 10 Minuten
STATE_FILE = Path("monitor_state.json")

# Diese Seiten dienen als Startpunkte.
# Eine Kategorie-Seite beweist NICHT den Bestand einer Filiale.
SOURCES = [
    {
        "name": "Müller",
        "store": "Korntal",
        "url": "https://www.mueller.de/b/pokemon/",
    },
    {
        "name": "Müller",
        "store": "Ditzingen",
        "url": "https://www.mueller.de/b/pokemon/",
    },
    {
        "name": "Thalia",
        "store": "Leonberg",
        "url": "https://www.thalia.de/",
    },
    {
        "name": "Rossmann",
        "store": "Gerlingen",
        "url": "https://www.rossmann.de/",
    },
]

# Begriffe, die auf einen möglichen Bestandswechsel hindeuten.
# Sie sind nur Hinweise und keine sichere Bestandsbestätigung.
AVAILABLE_TERMS = [
    "in den warenkorb",
    "jetzt kaufen",
    "lieferbar",
    "sofort verfügbar",
    "verfügbar",
    "vorbestellen",
    "add to cart",
]

UNAVAILABLE_TERMS = [
    "ausverkauft",
    "nicht verfügbar",
    "derzeit nicht lieferbar",
    "sold out",
    "out of stock",
]

POKEMON_TERMS = [
    "pokemon",
    "pokémon",
    "booster",
    "elite trainer box",
    "display",
    "tin",
    "kollektion",
    "sammelkarten",
]


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def send_discord(session, message):
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL fehlt.")

    async with session.post(
        DISCORD_WEBHOOK_URL,
        json={"content": message},
    ) as response:
        if response.status >= 300:
            detail = await response.text()
            raise RuntimeError(
                f"Discord HTTP {response.status}: {detail[:200]}"
            )


async def fetch_page(session, url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; PokemonRestockMonitor/1.0)"
        )
    }

    async with session.get(
        url,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=30),
        allow_redirects=True,
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")

        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            raise RuntimeError("Antwort ist keine HTML-Seite.")

        return await response.text()


def inspect_page(html):
    text = " ".join(html.lower().split())

    pokemon_found = any(term in text for term in POKEMON_TERMS)
    available_found = any(term in text for term in AVAILABLE_TERMS)
    unavailable_found = any(term in text for term in UNAVAILABLE_TERMS)

    if not pokemon_found:
        status = "no_pokemon_signal"
    elif unavailable_found:
        # Bei gemischten Treffern lieber keine Verfügbarkeit behaupten.
        status = "possibly_unavailable"
    elif available_found:
        status = "possible_availability"
    else:
        status = "unknown"

    # Nur zum Erkennen einer Seitenänderung, nicht als Produkt-ID.
    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()

    return status, fingerprint


async def check_source(session, source, state):
    key = source["name"] + "|" + source["store"] + "|" + source["url"]

    try:
        html = await fetch_page(session, source["url"])
        status, fingerprint = inspect_page(html)

        old = state.get(key, {})
        old_status = old.get("status")
        old_fingerprint = old.get("fingerprint")

        state[key] = {
            "status": status,
            "fingerprint": fingerprint,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        # Erster Lauf: Zustand speichern, aber nicht sofort alarmieren.
        if not old:
            print(f"Initial gespeichert: {key} ({status})")
            return

        # Nur bei einem Wechsel zu einem möglichen Verfügbarkeitssignal.
        if (
            status == "possible_availability"
            and old_status != "possible_availability"
        ):
            message = (
                "🎴 **Möglicher Pokémon-TCG-Verfügbarkeitshinweis**\n"
                f"**Händler:** {source['name']}\n"
                f"**Filiale/Region:** {source['store']}\n"
                "**Signal:** Verfügbarkeitsbegriffe auf der Seite erkannt\n"
                "**Status:** Nicht bestätigter Hinweis – Filialbestand "
                "nicht verifiziert\n"
                f"**Zeit:** {datetime.now().astimezone().isoformat()}\n"
                f"**Quelle:** {source['url']}"
            )
            await send_discord(session, message)
            print(f"Discord-Hinweis gesendet: {key}")

        elif old_fingerprint != fingerprint:
            print(f"Seitenänderung erkannt: {key} ({status})")
        else:
            print(f"Keine Änderung: {key} ({status})")

    except Exception as exc:
        # Fehler werden protokolliert, nicht als Restock gemeldet.
        print(f"Fehler bei {key}: {exc}")


async def main():
    if not DISCORD_WEBHOOK_URL:
        raise SystemExit(
            "Bitte DISCORD_WEBHOOK_URL in GitHub Actions als Secret setzen."
        )

    state = load_state()

    async with aiohttp.ClientSession() as session:
        # GitHub Actions startet den Prozess für jeden Lauf neu.
        # Deshalb wird hier einmal geprüft und anschließend beendet.
        for source in SOURCES:
            await check_source(session, source, state)

        save_state(state)


if __name__ == "__main__":
    asyncio.run(main())
