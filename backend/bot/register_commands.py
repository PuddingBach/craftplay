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
    global_command = {
        "name": "iniciar-player",
        "description": "Inicia a Activity CraftPlay nesta chamada",
        "type": 1,
        "contexts": [0, 1, 2],
        "integration_types": [0, 1],
    }
    targets = [(f"{root}/commands", global_command, "global")]
    if settings.discord_guild_id:
        guild_command = {key: value for key, value in global_command.items() if key not in {"contexts", "integration_types"}}
        targets.append((f"{root}/guilds/{settings.discord_guild_id}/commands", guild_command, "servidor de teste"))
    for endpoint, command, scope in targets:
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bot {settings.discord_bot_token}"},
            json=command,
            timeout=15,
        )
        if response.is_error:
            print(f"Discord respondeu {response.status_code} no escopo {scope}: {response.text}", file=sys.stderr)
            if scope == "global":
                raise SystemExit(1)
            continue
        registered = response.json()
        print(f"Comando /{registered['name']} registrado como {scope} com ID {registered['id']}.")


if __name__ == "__main__":
    register()
