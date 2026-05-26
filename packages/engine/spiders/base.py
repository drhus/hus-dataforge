from __future__ import annotations

from typing import Protocol

from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec


class Spider(Protocol):
    def run(self, slug: str, source: SourceSpec, progress: Progress) -> int:
        """Run the spider end-to-end. Returns number of records written."""
        ...
