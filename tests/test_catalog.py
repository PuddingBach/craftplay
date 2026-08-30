import pytest

from backend.providers.demo import DemoProvider


@pytest.mark.asyncio
async def test_demo_catalog_is_normalized_and_searchable():
    provider = DemoProvider()
    home = await provider.home()
    assert home["featured"]
    assert all(item.id and item.media_type for items in home.values() for item in items)
    results = await provider.search("animação")
    assert results


@pytest.mark.asyncio
async def test_missing_demo_item_is_safe():
    assert await DemoProvider().details("demo:missing") is None

