"""RQ worker entrypoint: `python -m packages.api.worker`."""
from __future__ import annotations

from rq import Worker

from packages.api.queue import get_queue, get_redis


def main() -> None:
    worker = Worker([get_queue()], connection=get_redis())
    worker.work()


if __name__ == "__main__":
    main()
