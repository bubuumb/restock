
import os
import aiohttp

async def discord_notify(message: str):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL ist nicht gesetzt")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            webhook_url,
            json={"content": message}
        ) as response:
            if response.status >= 300:
                raise RuntimeError(
                    f"Discord-Fehler: HTTP {response.status}"
                )
