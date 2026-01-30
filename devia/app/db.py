from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import pymysql


@dataclass
class DB:
    dsn: str

    def _conn_params(self) -> dict:
        parsed = urlparse(self.dsn)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": parsed.username,
            "password": parsed.password,
            "database": (parsed.path or "/").lstrip("/"),
        }

    def ping(self) -> bool:
        params = self._conn_params()
        with pymysql.connect(**params) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
