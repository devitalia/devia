from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import pymysql


# Query non consentite in read-only (solo SELECT)
_FORBIDDEN_SQL = (
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
    "TRUNCATE", "GRANT", "REVOKE", "EXEC", "EXECUTE", "CALL",
)


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

    def get_table_names(self) -> list[str]:
        """Elenco nomi tabelle (per manifest / indice)."""
        params = self._conn_params()
        db = params["database"]
        with pymysql.connect(**params) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT TABLE_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = %s
                    ORDER BY TABLE_NAME
                    """,
                    (db,),
                )
                return [row[0] for row in cur.fetchall()]

    def get_schema(self) -> str:
        """Schema tabelle e colonne dal DB (per contesto LLM)."""
        params = self._conn_params()
        db = params["database"]
        with pymysql.connect(**params) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = %s
                    ORDER BY TABLE_NAME, ORDINAL_POSITION
                    """,
                    (db,),
                )
                rows = cur.fetchall()
        # Raggruppa per tabella
        by_table: dict[str, list[str]] = {}
        for table, col, dtype, nullable in rows:
            by_table.setdefault(table, []).append(f"  - {col} ({dtype})")
        lines = [f"- **{t}**:\n" + "\n".join(cols) for t, cols in sorted(by_table.items())]
        return "\n".join(lines) if lines else "(nessuna tabella)"

    def execute_read_only(self, query: str, max_rows: int = 500) -> list[dict]:
        """Esegue solo SELECT; restituisce righe come liste di dict. Aggiunge LIMIT se manca."""
        q = query.strip()
        if not q.upper().startswith("SELECT"):
            raise ValueError("Solo query SELECT consentite")
        for bad in _FORBIDDEN_SQL:
            if bad in q.upper():
                raise ValueError(f"Operazione non consentita: {bad}")
        if "LIMIT" not in q.upper():
            q = q.rstrip(";").strip() + f" LIMIT {max_rows}"
        params = self._conn_params()
        with pymysql.connect(**params) as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute(q)
                return cur.fetchall()
