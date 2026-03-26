from __future__ import annotations

import json
import sqlite3

from .models import Paper
from .utils import utc_now


def db_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS papers (
          source TEXT NOT NULL,
          paper_id TEXT NOT NULL,
          title TEXT NOT NULL,
          url TEXT NOT NULL,
          published_at TEXT,
          authors_json TEXT NOT NULL,
          summary TEXT,
          tags_json TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          PRIMARY KEY (source, paper_id)
        )
        """
    )
    return conn


def db_seen(conn: sqlite3.Connection, p: Paper) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM papers WHERE source=? AND paper_id=? LIMIT 1",
        (p.source, p.id),
    )
    return cur.fetchone() is not None


def db_insert(conn: sqlite3.Connection, p: Paper) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO papers (
          source, paper_id, title, url, published_at, authors_json, summary, tags_json, first_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            p.source,
            p.id,
            p.title,
            p.url,
            p.published_at,
            json.dumps(p.authors, ensure_ascii=False),
            p.summary,
            json.dumps(p.tags, ensure_ascii=False),
            utc_now().isoformat(),
        ),
    )

