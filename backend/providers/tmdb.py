import httpx

from backend.providers.base import MetadataProvider
from backend.schemas import ExternalIds, MediaItem


class TMDBProvider(MetadataProvider):
    name = "tmdb"
    api_root = "https://api.themoviedb.org/3"
    image_root = "https://image.tmdb.org/t/p"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def _get(self, path: str, **params) -> dict:
        params.update({"api_key": self.api_key, "language": "pt-BR"})
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(f"{self.api_root}{path}", params=params)
            response.raise_for_status()
            return response.json()

    def _normalize(self, raw: dict, forced_type: str | None = None) -> MediaItem:
        tmdb_type = forced_type or raw.get("media_type", "movie")
        media_type = "series" if tmdb_type == "tv" else "movie"
        release = raw.get("release_date") or raw.get("first_air_date") or ""
        title = raw.get("title") or raw.get("name") or "Sem título"
        return MediaItem(
            id=f"tmdb:{tmdb_type}:{raw['id']}",
            external_ids=ExternalIds(tmdb=raw["id"]),
            title=title,
            original_title=raw.get("original_title") or raw.get("original_name") or title,
            overview=raw.get("overview", ""), media_type=media_type,
            genres=[genre["name"] for genre in raw.get("genres", [])],
            poster=f"{self.image_root}/w500{raw['poster_path']}" if raw.get("poster_path") else None,
            backdrop=f"{self.image_root}/original{raw['backdrop_path']}" if raw.get("backdrop_path") else None,
            year=int(release[:4]) if len(release) >= 4 else None,
            rating=raw.get("vote_average", 0), popularity=raw.get("popularity", 0),
            duration=raw.get("runtime"), status=raw.get("status"),
        )

    async def home(self) -> dict[str, list[MediaItem]]:
        trending = await self._get("/trending/all/week")
        movies = await self._get("/movie/popular")
        series = await self._get("/tv/popular")
        normalized_trending = [self._normalize(item) for item in trending.get("results", []) if item.get("media_type") in {"movie", "tv"}]
        return {
            "featured": normalized_trending[:5], "trending": normalized_trending,
            "movies": [self._normalize(item, "movie") for item in movies.get("results", [])],
            "series": [self._normalize(item, "tv") for item in series.get("results", [])],
            "anime": [], "cartoons": [], "releases": normalized_trending,
        }

    async def search(self, query: str, page: int = 1) -> list[MediaItem]:
        data = await self._get("/search/multi", query=query, page=page, include_adult="false")
        return [self._normalize(item) for item in data.get("results", []) if item.get("media_type") in {"movie", "tv"}]

    async def details(self, media_id: str) -> MediaItem | None:
        _, kind, raw_id = media_id.split(":", 2)
        data = await self._get(f"/{kind}/{raw_id}", append_to_response="credits,videos,content_ratings,release_dates,external_ids")
        item = self._normalize(data, kind)
        item.external_ids.imdb = data.get("external_ids", {}).get("imdb_id") or data.get("imdb_id")
        item.cast = [person["name"] for person in data.get("credits", {}).get("cast", [])[:10]]
        directors = [person["name"] for person in data.get("credits", {}).get("crew", []) if person.get("job") == "Director"]
        item.director = directors[0] if directors else None
        trailers = [video for video in data.get("videos", {}).get("results", []) if video.get("site") == "YouTube" and video.get("type") == "Trailer"]
        item.trailer = f"https://www.youtube.com/watch?v={trailers[0]['key']}" if trailers else None
        return item

    async def recommendations(self, media_id: str) -> list[MediaItem]:
        _, kind, raw_id = media_id.split(":", 2)
        data = await self._get(f"/{kind}/{raw_id}/recommendations")
        return [self._normalize(item, kind) for item in data.get("results", [])[:12]]
