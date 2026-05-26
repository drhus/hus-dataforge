from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from packages.api.settings import DB_PATH, ensure_dirs


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # scrape | clean | export
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    rq_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        ensure_dirs()
        _engine = create_engine(
            f"sqlite:///{DB_PATH}", future=True, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(_engine)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session() -> Iterator[Session]:
    if _SessionLocal is None:
        engine()
    assert _SessionLocal is not None
    with _SessionLocal() as session:
        yield session
