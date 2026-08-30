import asyncio
import logging

import httpx

from backend.schemas import MediaItem


class AnimeMetadataResolver:
    """Adds AniList/Jikan title aliases to TMDB anime metadata; never returns video."""

    async def resolve(self, media: MediaItem) -> list[str]:
        if media.media_type != "anime":
            return [media.title, media.original_title]
        anilist, jikan = await asyncio.gather(self._anilist(media.title), self._jikan(media.title))
        values = [media.title, media.original_title, *anilist, *jikan]
        return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))

    async def _anilist(self, title: str) -> list[str]:
        query = "query ($search: String) { Media(search: $search, type: ANIME) { title { romaji english native } synonyms } }"
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.post("https://graphql.anilist.co", json={"query": query, "variables": {"search": title}})
                response.raise_for_status()
            media = response.json().get("data", {}).get("Media") or {}
            return [*(media.get("title") or {}).values(), *(media.get("synonyms") or [])]
        except (httpx.HTTPError, ValueError):
            logging.getLogger("craftplay.metadata.anime").info("AniList aliases unavailable for %s", title)
            return []

    async def _jikan(self, title: str) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get("https://api.jikan.moe/v4/anime", params={"q": title, "limit": 1})
                response.raise_for_status()
            item = (response.json().get("data") or [{}])[0]
            return [item.get("title"), item.get("title_english"), item.get("title_japanese"), *(item.get("title_synonyms") or [])]
        except (httpx.HTTPError, ValueError, IndexError):
            logging.getLogger("craftplay.metadata.anime").info("Jikan aliases unavailable for %s", title)
            return []
