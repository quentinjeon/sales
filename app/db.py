# -*- coding: utf-8 -*-
"""DB 연결."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("CECNR_DB", ROOT / "data" / "cecnr.db"))
UPLOAD_DIR = Path(os.environ.get("CECNR_UPLOADS", ROOT / "data" / "uploads"))


def make_engine(url: str | None = None):
    if url is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{DB_PATH}"
    engine = create_engine(url, future=True)

    # SQLite는 기본적으로 외래키를 강제하지 않는다 — 켜 준다.
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(conn, _rec):
            conn.execute("PRAGMA foreign_keys=ON")

    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
