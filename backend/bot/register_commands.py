"""Register /iniciar-player with Discord.

Run once after configuring DISCORD_CLIENT_ID and DISCORD_BOT_TOKEN.
"""

import sys

import httpx

from backend.config import get_settings


def register() -> None:
    settings = get_settings()
    if not settings.discord_client_id or not settings.discord_bot_token:
        raise SystemExit("Configure DISCORD_CLIENT_ID e DISCORD_BOT_TOKEN no .env")
    root = f"https://discord.com/api/v10/applications/{settings.discord_client_id}"
    endpoint = f"{root}/guilds/{settings.discord_guild_id}/commands" if settings.discord_guild_id else f"{root}/commands"
    command = {
        "name": "iniciar-player",
        "description": "Inicia a Activity CraftPlay nesta chamada",
        "type": 1,
    }
    if not settings.discord_guild_id:
        command.update({"contexts": [0, 1, 2], "integration_types": [0, 1]})
    response = httpx.post(
        endpoint,
        headers={"Authorization": f"Bot {settings.discord_bot_token}"},
        json=command,
        timeout=15,
    )
    if response.is_error:
        print(f"Discord respondeu {response.status_code}: {response.text}", file=sys.stderr)
        raise SystemExit(1)
    registered = response.json()
    print(f"Comando /{registered['name']} registrado com ID {registered['id']}.")


if __name__ == "__main__":
    register()
