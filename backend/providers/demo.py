from datetime import date

from backend.providers.base import MetadataProvider
from backend.schemas import Episode, ExternalIds, MediaItem, Season


IMAGE_ROOT = "https://download.blender.org/demo/movies"


DEMO_ITEMS = [
    MediaItem(
        id="demo:big-buck-bunny",
        external_ids=ExternalIds(provider="blender-open-movie"),
        title="Big Buck Bunny",
        original_title="Big Buck Bunny",
        overview="Um coelho gentil decide reagir quando três roedores transformam sua manhã tranquila em caos.",
        media_type="movie",
        genres=["Animação", "Comédia", "Família"],
        poster="/demo/big-buck-bunny.svg", backdrop="/demo/big-buck-bunny.svg",
        release_date=date(2008, 4, 10), year=2008, duration=10, rating=8.4, popularity=99,
        cast=["Bunny", "Frank", "Rinky", "Gamera"], director="Sacha Goedegebure",
        certification="Livre", status="Lançado", tags=["open-movie", "featured"],
    ),
    MediaItem(
        id="demo:sintel",
        external_ids=ExternalIds(provider="blender-open-movie"),
        title="Sintel", original_title="Sintel",
        overview="Uma jovem guerreira cruza um mundo fantástico à procura do dragão que salvou quando filhote.",
        media_type="anime", genres=["Fantasia", "Aventura", "Animação"],
        poster="/demo/sintel.svg", backdrop="/demo/sintel.svg",
        release_date=date(2010, 9, 27), year=2010, duration=15, rating=8.8, popularity=96,
        cast=["Halina Reijn", "Thom Hoffman"], director="Colin Levy", certification="10",
        status="Lançado", tags=["open-movie", "featured"],
    ),
    MediaItem(
        id="demo:tears-of-steel",
        external_ids=ExternalIds(provider="blender-open-movie"),
        title="Tears of Steel", original_title="Tears of Steel",
        overview="Cientistas e guerreiros se reúnem em uma igreja de Amsterdã para impedir um futuro dominado por robôs.",
        media_type="movie", genres=["Ficção científica", "Ação"],
        poster="/demo/tears-of-steel.svg", backdrop="/demo/tears-of-steel.svg",
        release_date=date(2012, 9, 26), year=2012, duration=12, rating=8.1, popularity=88,
        cast=["Derek de Lint", "Sergio Hasselbaink", "Vanja Rukavina"], director="Ian Hubert",
        certification="12", status="Lançado", tags=["open-movie"],
    ),
    MediaItem(
        id="demo:elephants-dream",
        external_ids=ExternalIds(provider="blender-open-movie"),
        title="Elephants Dream", original_title="Elephants Dream",
        overview="Emo e Proog exploram uma máquina surreal e gigantesca onde cada sala desafia a lógica.",
        media_type="series", genres=["Animação", "Fantasia", "Experimental"],
        poster="/demo/elephants-dream.svg", backdrop="/demo/elephants-dream.svg",
        release_date=date(2006, 3, 24), year=2006, duration=11, rating=7.9, popularity=82,
        cast=["Cas Jansen", "Tygo Gernandt"], director="Bassam Kurdali", certification="Livre",
        status="Finalizada", tags=["open-movie"],
        seasons=[Season(number=1, title="Temporada 1", episodes=[
            Episode(id="demo:elephants-dream:s1:e1", number=1, title="A Máquina", overview="Proog conduz Emo pelas salas de uma máquina impossível.", duration=11),
            Episode(id="demo:elephants-dream:s1:e2", number=2, title="Nos bastidores", overview="Uma seleção demonstrativa sobre a criação do filme aberto.", duration=4),
        ])],
    ),
    MediaItem(
        id="demo:spring",
        external_ids=ExternalIds(provider="blender-open-movie"),
        title="Spring", original_title="Spring",
        overview="Uma pastora e seu cão enfrentam antigos espíritos para completar o ciclo das estações.",
        media_type="cartoon", genres=["Animação", "Fantasia", "Família"],
        poster="/demo/spring.svg", backdrop="/demo/spring.svg",
        release_date=date(2019, 4, 4), year=2019, duration=8, rating=8.7, popularity=92,
        director="Andy Goralczyk", certification="Livre", status="Lançado", tags=["open-movie", "featured"],
        seasons=[Season(number=1, title="Especiais", episodes=[
            Episode(id="demo:spring:s1:e1", number=1, title="Spring", overview="A chegada da primavera em um mundo mágico.", duration=8),
        ])],
    ),
    MediaItem(
        id="demo:cosmos-laundromat",
        external_ids=ExternalIds(provider="blender-open-movie"),
        title="Cosmos Laundromat", original_title="Cosmos Laundromat: First Cycle",
        overview="Em uma ilha desolada, uma ovelha encontra um vendedor misterioso que promete uma vida inteiramente nova.",
        media_type="cartoon", genres=["Animação", "Aventura", "Comédia"],
        poster="/demo/cosmos-laundromat.svg", backdrop="/demo/cosmos-laundromat.svg",
        release_date=date(2015, 8, 10), year=2015, duration=12, rating=8.3, popularity=78,
        director="Mathieu Auvray", certification="Livre", status="Especial", tags=["open-movie"],
    ),
]


class DemoProvider(MetadataProvider):
    name = "demo"

    async def home(self) -> dict[str, list[MediaItem]]:
        popular = sorted(DEMO_ITEMS, key=lambda item: item.popularity, reverse=True)
        return {
            "featured": [item for item in DEMO_ITEMS if "featured" in item.tags],
            "trending": sorted(DEMO_ITEMS, key=lambda item: item.rating, reverse=True),
            "movies": [item for item in popular if item.media_type == "movie"],
            "series": [item for item in popular if item.media_type == "series"],
            "anime": [item for item in popular if item.media_type == "anime"],
            "cartoons": [item for item in popular if item.media_type == "cartoon"],
            "releases": sorted(DEMO_ITEMS, key=lambda item: item.year or 0, reverse=True),
        }

    async def search(self, query: str, page: int = 1) -> list[MediaItem]:
        needle = query.casefold()
        return [item for item in DEMO_ITEMS if needle in (item.title + " " + " ".join(item.genres)).casefold()]

    async def details(self, media_id: str) -> MediaItem | None:
        return next((item for item in DEMO_ITEMS if item.id == media_id), None)

    async def recommendations(self, media_id: str) -> list[MediaItem]:
        current = await self.details(media_id)
        if not current:
            return []
        return [item for item in DEMO_ITEMS if item.id != media_id and set(item.genres) & set(current.genres)][:6]
