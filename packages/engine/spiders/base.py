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
        force: bool = False,
    ) -> int:
        """Run the spider end-to-end. Returns number of records written.

        `run_id` — API Job.id; spiders pass it to RecordWriter for lineage.
        `force` — if True, scrape from scratch (ignore incremental
                  checkpoints / seen-URL set). Default False = resume."""
        ...
