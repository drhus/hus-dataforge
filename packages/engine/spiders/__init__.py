from packages.engine.spiders.base import Spider
from packages.engine.spiders.fixture import FixtureSpider
from packages.engine.spiders.list_detail import ListDetailSpider
from packages.engine.spiders.multi_level_list_detail import MultiLevelListDetailSpider
from packages.engine.spiders.paginated import PaginatedSpider
from packages.engine.spiders.telegram_mtproto import TelegramMTProtoSpider
from packages.engine.spiders.telegram_web import TelegramWebSpider
from packages.engine.spiders.x_syndication import XSyndicationSpider
from packages.engine.spiders.youtube_channel import YouTubeChannelSpider

REGISTRY: dict[str, type[Spider]] = {
    "paginated": PaginatedSpider,
    "fixture": FixtureSpider,
    "list_detail": ListDetailSpider,
    "multi_level_list_detail": MultiLevelListDetailSpider,
    "telegram_web": TelegramWebSpider,
    "telegram_mtproto": TelegramMTProtoSpider,
    "x_syndication": XSyndicationSpider,
    "youtube_channel": YouTubeChannelSpider,
}

__all__ = [
    "Spider",
    "PaginatedSpider",
    "FixtureSpider",
    "ListDetailSpider",
    "MultiLevelListDetailSpider",
    "TelegramWebSpider",
    "TelegramMTProtoSpider",
    "XSyndicationSpider",
    "YouTubeChannelSpider",
    "REGISTRY",
]
