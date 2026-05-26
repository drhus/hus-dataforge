from packages.engine.spiders.base import Spider
from packages.engine.spiders.fixture import FixtureSpider
from packages.engine.spiders.list_detail import ListDetailSpider
from packages.engine.spiders.paginated import PaginatedSpider

REGISTRY: dict[str, type[Spider]] = {
    "paginated": PaginatedSpider,
    "fixture": FixtureSpider,
    "list_detail": ListDetailSpider,
}

__all__ = ["Spider", "PaginatedSpider", "FixtureSpider", "ListDetailSpider", "REGISTRY"]
