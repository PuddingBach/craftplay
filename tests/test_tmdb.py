import pytest

from backend.providers.tmdb import TMDBProvider


@pytest.mark.asyncio
async def test_tmdb_home_imports_all_catalog_sections(monkeypatch):
    provider = TMDBProvider(read_access_token="token")

    async def fake_get(path, **params):
        item = {
            "id": abs(hash((path, tuple(params.items())))) % 100000,
            "title": "Filme importado",
            "name": "Série importada",
            "media_type": "movie",
            "release_date": "2026-08-30",
            "first_air_date": "2026-08-30",
            "vote_average": 8.5,
        }
        return {"results": [item]}

    monkeypatch.setattr(provider, "_get", fake_get)
    sections = await provider.home()

    assert sections["movies"]
    assert sections["series"]
    assert sections["anime"][0].media_type == "anime"
    assert sections["cartoons"][0].media_type == "cartoon"
    assert sections["releases"]
