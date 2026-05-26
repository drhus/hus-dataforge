"""Progress reporting. Two implementations:

- NullProgress: drop everything (used in tests).
- DBProgress: write counters + last_url into the Job row's `message` JSON.

Engine code only uses the Progress protocol — callers pick the impl."""
from __future__ import annotations

import json
from typing import Protocol

from sqlalchemy.orm import Session

from packages.api.db import Job


class Progress(Protocol):
    def start(self, source: str) -> None: ...
    def page(self, url: str, records_on_page: int) -> None: ...
    def finish(self) -> None: ...

    @property
    def total_records(self) -> int: ...
    @property
    def last_url(self) -> str | None: ...


class NullProgress:
    total_records = 0
    last_url: str | None = None

    def start(self, source: str) -> None:
        return None

    def page(self, url: str, records_on_page: int) -> None:
        return None

    def finish(self) -> None:
        return None


class DBProgress:
    """Writes a compact JSON blob into Job.message."""

    def __init__(self, session: Session, job_id: int):
        self.session = session
        self.job_id = job_id
        self.total_records = 0
        self.pages = 0
        self.last_url: str | None = None
        self.current_source: str | None = None
        self._flush()

    def start(self, source: str) -> None:
        self.current_source = source
        self.pages = 0
        self._flush()

    def page(self, url: str, records_on_page: int) -> None:
        self.last_url = url
        self.pages += 1
        self.total_records += records_on_page
        self._flush()

    def finish(self) -> None:
        self._flush()

    def _flush(self) -> None:
        job = self.session.get(Job, self.job_id)
        if not job:
            return
        job.message = json.dumps(
            {
                "source": self.current_source,
                "pages": self.pages,
                "records": self.total_records,
                "last_url": self.last_url,
            },
            ensure_ascii=False,
        )
        self.session.commit()
