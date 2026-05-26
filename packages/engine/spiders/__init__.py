from packages.engine.spiders.base import Spider
from packages.engine.spiders.fixture import FixtureSpider
from packages.engine.spiders.list_detail import ListDetailSpider
from packages.engine.spiders.paginated import PaginatedSpider
from packages.engine.spiders.telegram_mtproto import TelegramMTProtoSpider
from packages.engine.spiders.telegram_web import TelegramWebSpider
from packages.engine.spiders.x_syndication import XSyndicationSpider

REGISTRY: dict[str, type[Spider]] = {
    "paginated": PaginatedSpider,
    "fixture": FixtureSpider,
    "list_detail": ListDetailSpider,
    "telegram_web": TelegramWebSpider,
    "telegram_mtproto": TelegramMTProtoSpider,
    "x_syndication": XSyndicationSpider,
}

__all__ = [
    "Spider",
    "PaginatedSpider",
    "FixtureSpider",
    "ListDetailSpider",
    "TelegramWebSpider",
    "TelegramMTProtoSpider",
    "XSyndicationSpider",
    "REGISTRY",
]
