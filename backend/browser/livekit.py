from datetime import datetime, timedelta, timezone

from jose import jwt

from backend.config import get_settings


def livekit_configured() -> bool:
    settings = get_settings()
    return bool(settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret)


def create_viewer_token(room_name: str, identity: str, name: str, *, can_publish: bool = False) -> str:
    settings = get_settings()
    if not livekit_configured():
        raise RuntimeError("LiveKit nao configurado")
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings.livekit_api_key,
        "sub": identity,
        "name": name,
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(hours=2)).timestamp()),
        "video": {
            "roomJoin": True,
            "room": room_name,
            "canSubscribe": True,
            "canPublish": can_publish,
            "canPublishData": True,
        },
    }
    return jwt.encode(payload, settings.livekit_api_secret, algorithm="HS256")


async def set_room_privacy(room_name: str, host_identity: str, enabled: bool) -> None:
    """Revoke or restore subscriptions for every viewer except the host."""
    if not livekit_configured():
        return
    try:
        from livekit import api
        settings = get_settings()
        api_url = settings.livekit_url.replace("wss://", "https://").replace("ws://", "http://")
        async with api.LiveKitAPI(api_url, settings.livekit_api_key, settings.livekit_api_secret) as client:
            response = await client.room.list_participants(api.ListParticipantsRequest(room=room_name))
            for participant in response.participants:
                if participant.identity == host_identity or participant.identity.startswith("browser-"):
                    continue
                await client.room.update_participant(api.UpdateParticipantRequest(
                    room=room_name, identity=participant.identity,
                    permission=api.ParticipantPermission(can_subscribe=not enabled, can_publish=False, can_publish_data=True),
                ))
    except Exception as exc:
        raise RuntimeError("Nao foi possivel aplicar privacidade no LiveKit") from exc
