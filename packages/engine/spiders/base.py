from __future__ import annotations

from typing import Protocol

from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec


class Spider(Protocol):
    def run(
        self,
        slug: str,
        source: SourceSpec,
        progress: Progress,
        *,
        run_id: int | None = None,
    ) -> int:
        """Run the spider end-to-end. Returns number of records written.

        `run_id` is the API Job.id; spiders that pass it to RecordWriter
        will stamp each written record for lineage."""
        ...
