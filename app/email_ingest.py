from __future__ import annotations

import base64
import csv
import imaplib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime, parseaddr
from io import StringIO
from pathlib import Path
from typing import Any

import requests
import yaml

from app.config import settings


@dataclass
class SenderRule:
    email: str
    supplier_id: int = 0
    require_csv: bool = False
    require_pdf: bool = False
    enabled: bool = True


def _parse_yyyy_mm_dd(value: str, fallback: date) -> date:
    raw = (value or "").strip()
    if not raw:
        return fallback
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return fallback


def _to_imap_since(date_value: date) -> str:
    return date_value.strftime("%d-%b-%Y")


def _load_sender_rules() -> dict[str, SenderRule]:
    rules_path = Path(settings.senders_yaml_path)
    if not rules_path.exists():
        return {}

    content = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    sender_items = content.get("senders", [])

    rules: dict[str, SenderRule] = {}
    for item in sender_items:
        sender_email = str(item.get("email", "")).strip().lower()
        if not sender_email:
            continue
        rules[sender_email] = SenderRule(
            email=sender_email,
            supplier_id=int(item.get("supplier_id") or 0),
            require_csv=bool(item.get("require_csv", False)),
            require_pdf=bool(item.get("require_pdf", False)),
            enabled=bool(item.get("enabled", True)),
        )
    return rules


def _init_db() -> sqlite3.Connection:
    db_path = Path(settings.mail_state_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_messages (
            uid TEXT PRIMARY KEY,
            message_id TEXT,
            sender TEXT NOT NULL,
            subject TEXT,
            received_at TEXT,
            processed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_processed_message_id ON processed_messages(message_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _already_processed(conn: sqlite3.Connection, uid: str, message_id: str | None) -> bool:
    if message_id:
        row = conn.execute(
            "SELECT 1 FROM processed_messages WHERE uid = ? OR message_id = ? LIMIT 1",
            (uid, message_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM processed_messages WHERE uid = ? LIMIT 1",
            (uid,),
        ).fetchone()
    return row is not None


def _mark_processed(
    conn: sqlite3.Connection,
    *,
    uid: str,
    message_id: str | None,
    sender: str,
    subject: str,
    received_at: datetime,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO processed_messages (
            uid, message_id, sender, subject, received_at, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            uid,
            message_id,
            sender,
            subject,
            received_at.isoformat(),
            datetime.now(UTC).isoformat(),
        ),
    )
    conn.commit()


def _parse_received_at(email_message: Message, fallback: datetime) -> datetime:
    date_header = email_message.get("Date")
    if not date_header:
        return fallback
    try:
        parsed = parsedate_to_datetime(date_header)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return fallback


def _extract_flags(email_message: Message) -> tuple[bool, bool]:
    def _decoded_filename(value: str | None) -> str:
        if not value:
            return ""
        chunks = decode_header(value)
        parts: list[str] = []
        for chunk, encoding in chunks:
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(encoding or "utf-8", errors="ignore"))
            else:
                parts.append(chunk)
        return "".join(parts).strip().lower()

    has_csv = False
    has_pdf = False
    for part in email_message.walk():
        filename = _decoded_filename(part.get_filename())
        content_type = (part.get_content_type() or "").lower()
        if not filename:
            if content_type == "application/pdf":
                has_pdf = True
            elif content_type in {"text/csv", "application/csv"}:
                has_csv = True
            continue
        if filename.endswith(".csv"):
            has_csv = True
        elif filename.endswith(".pdf"):
            has_pdf = True
    return has_csv, has_pdf


def _extract_attachments(email_message: Message) -> tuple[str, bytes | None, str]:
    def _decoded_filename(value: str | None) -> str:
        if not value:
            return ""
        chunks = decode_header(value)
        parts: list[str] = []
        for chunk, encoding in chunks:
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(encoding or "utf-8", errors="ignore"))
            else:
                parts.append(chunk)
        return "".join(parts).strip()

    csv_text = ""
    pdf_bytes: bytes | None = None
    pdf_filename = ""

    for part in email_message.walk():
        filename = _decoded_filename(part.get_filename())
        filename_l = filename.lower()
        content_type = (part.get_content_type() or "").lower()
        payload = part.get_payload(decode=True)
        if not payload:
            continue

        if not csv_text and (filename_l.endswith(".csv") or content_type in {"text/csv", "application/csv"}):
            csv_text = payload.decode("utf-8", errors="ignore")
            continue

        if pdf_bytes is None and (filename_l.endswith(".pdf") or content_type == "application/pdf"):
            pdf_bytes = payload
            pdf_filename = filename or "documento.pdf"

    return csv_text, pdf_bytes, pdf_filename


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", key.lower())


def _pick_value(row: dict[str, str], candidates: list[str]) -> str:
    normalized_map = {_normalize_key(k): str(v).strip() for k, v in row.items()}
    for candidate in candidates:
        value = normalized_map.get(_normalize_key(candidate), "")
        if value:
            return value
    return ""


def _to_iso_date(value: str) -> str:
    value = (value or "").strip()
    match = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", value)
    if match:
        dd, mm, yyyy = match.groups()
        return f"{yyyy}-{mm}-{dd}"
    return value


def _to_decimal(value: str) -> Decimal:
    s = (value or "").strip().replace(" ", "").replace("€", "")
    if not s:
        return Decimal("0")
    # Notazione scientifica (es. 5,19E+09 da Excel italiano): non rimuovere il punto decimale.
    if re.search(r"[eE][+-]?\d+", s):
        s = s.replace(",", ".")
        s = re.sub(r"[^0-9eE.+-]", "", s)
    else:
        s = s.replace(".", "").replace(",", ".")
        s = re.sub(r"[^0-9.-]", "", s)
    if not s:
        return Decimal("0")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def _format_decimal_it(value: Decimal, decimals: int = 2) -> str:
    quant = Decimal("1").scaleb(-decimals)
    try:
        normalized = value.quantize(quant)
    except InvalidOperation:
        normalized = value
    return f"{normalized}".replace(".", ",")


def _payload_for_intranet(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "token": (record.get("token") or "").strip(),
        "supplier_id": int(record.get("supplier_id") or 0),
        "testata": dict(record.get("testata") or {}),
        "righe": [
            {
                "n": str(line.get("n", "")),
                "codice_articolo": str(line.get("codice_articolo", "")),
                "descrizione": str(line.get("descrizione", "")),
                "quantita": str(line.get("quantita", "")),
                "prezzo_unitario": str(line.get("prezzo_unitario", "")),
                "importo": str(line.get("importo", "")),
                "uom": str(line.get("uom", "")),
            }
            for line in (record.get("righe") or [])
        ],
    }


def _post_record_to_intranet(record: dict[str, Any]) -> dict[str, Any]:
    return _post_to_intranet(_payload_for_intranet(record))


def _records_from_csv(csv_text: str, supplier_id: int, pdf_bytes: bytes | None) -> list[dict[str, Any]]:
    if not csv_text.strip():
        return []

    delimiter = ";"
    sample = csv_text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,|\t").delimiter
    except Exception:  # noqa: BLE001
        delimiter = ";"

    reader = csv.DictReader(StringIO(csv_text), delimiter=delimiter)
    if not reader.fieldnames:
        return []

    grouped: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(reader, start=1):
        if not row:
            continue

        # Sonepar / export Excel: "Numero D" = DDT, "Numero C" = altro riferimento; evitare di usare "numero c" come DDT.
        numero_documento = _pick_value(
            row,
            [
                "numeroddt",
                "numerod",
                "numero ddt",
                "numero documento",
                "numero",
            ],
        )
        data_documento = _to_iso_date(
            _pick_value(
                row,
                ["dataddt", "data ddt", "data documento", "data"],
            )
        )
        numero_riferimento = _pick_value(
            row,
            [
                "mioriferimento",
                "mioriferi",
                "mio riferimento",
                "mio riferi",
                "riferimento ordine",
                "riferimento",
            ],
        ) or numero_documento
        key = f"{numero_documento}|{data_documento}"

        if key not in grouped:
            grouped[key] = {
                "token": (settings.intranet_api_token or "").strip(),
                "supplier_id": supplier_id,
                "testata": {
                    "numero_riferimento": numero_riferimento,
                    "numero_documento": numero_documento,
                    "data_documento": data_documento,
                    "numero_ordine_interno": _pick_value(row, ["numeroordine", "numero ordine"]),
                    "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii") if pdf_bytes else "",
                },
                "righe": [],
                "__total": Decimal("0"),
            }

        # Sonepar: "Qta' Conse" -> qtaconse; "Valore con" -> valorecon
        quantita = _pick_value(
            row,
            [
                "qtaconsegnata",
                "qtaconse",
                "qtacons",
                "qta cons",
                "qta conse",
                "qta consegnata",
                "qtaordin",
                "qta ordi",
                "qta ordine",
                "quantita consegnata",
                "quantita",
                "quantità",
                "qta",
            ],
        )
        prezzo_unitario = _pick_value(
            row,
            [
                "prezzoxmolt",
                "prezzo x molt",
                "prezzo x molt.",
                "prezzoxn",
                "prezzo x n",
                "prezzo unitario",
                "prezzo",
            ],
        )
        importo = _pick_value(
            row,
            [
                "valoreconsegna",
                "valoreconsegnato",
                "valorecon",
                "valore cons",
                "valore c",
                "importo riga",
                "importo",
                "totale riga",
                "totale",
            ],
        )
        codice = _pick_value(row, ["codprodotto", "codprod", "cod. prod", "codice articolo", "articolo"])
        descrizione = _pick_value(row, ["descrizione", "descrizio"])
        if not codice and not descrizione and not quantita and not importo:
            continue

        imp_dec = _to_decimal(importo)
        pre_dec_raw = _to_decimal(prezzo_unitario)
        qty_dec = _to_decimal(quantita)

        # Prezzo unitario reale: sempre derivato da importo/quantita quando possibile.
        pre_dec = Decimal("0")
        if qty_dec > 0 and imp_dec > 0:
            try:
                pre_dec = imp_dec / qty_dec
            except (InvalidOperation, ArithmeticError):
                pre_dec = Decimal("0")
        if pre_dec <= 0:
            pre_dec = pre_dec_raw
        if pre_dec <= 0:
            continue
        if not quantita and imp_dec > 0 and pre_dec > 0:
            try:
                q = imp_dec / pre_dec
                quantita = str(q.quantize(Decimal("0.001")))
                qty_dec = _to_decimal(quantita)
            except (InvalidOperation, ArithmeticError):
                pass

        line_mismatch = False
        if qty_dec > 0 and imp_dec > 0 and pre_dec_raw > 0:
            expected = pre_dec_raw * qty_dec
            # Tolleranza minima per arrotondamenti.
            delta = abs(expected - imp_dec)
            line_mismatch = delta > Decimal("0.05")

        # Totale documento: somma solo delle righe con importo positivo.
        if imp_dec > 0:
            grouped[key]["__total"] += imp_dec
        grouped[key]["__has_line_mismatch"] = bool(grouped[key].get("__has_line_mismatch")) or line_mismatch
        grouped[key]["righe"].append(
            {
                "n": str(idx),
                "codice_articolo": codice,
                "descrizione": descrizione,
                "quantita": quantita,
                "prezzo_unitario": _format_decimal_it(pre_dec, 5),
                "importo": importo,
                "uom": _pick_value(row, ["um", "u.m.", "u.m"]),
            }
        )

    records: list[dict[str, Any]] = []
    for record in grouped.values():
        if not record["righe"]:
            continue
        record["testata"]["totale_documento"] = _format_decimal_it(record.pop("__total"), 2)
        records.append(record)
    return records


def _post_to_intranet(payload: dict[str, Any]) -> dict[str, Any]:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    response = requests.post(
        settings.intranet_api_url,
        json=payload,
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        return {"raw_response": response.text}


def _set_last_email_uid(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute(
        """
        INSERT INTO state_meta(key, value, updated_at)
        VALUES ('last_email_uid', ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (uid, datetime.now(UTC).isoformat()),
    )
    conn.commit()


def _get_last_email_uid(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM state_meta WHERE key = 'last_email_uid' LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return str(row[0]).strip() or None


def list_processed_messages() -> dict[str, Any]:
    conn = _init_db()
    try:
        last_uid = _get_last_email_uid(conn)
        rows = conn.execute(
            """
            SELECT
                rowid AS id,
                uid,
                message_id,
                sender,
                subject,
                received_at,
                processed_at
            FROM processed_messages
            ORDER BY rowid DESC
            """
        ).fetchall()
    finally:
        conn.close()

    items = [
        {
            "id": row[0],
            "uid": row[1],
            "message_id": row[2],
            "sender": row[3],
            "subject": row[4],
            "received_at": row[5],
            "processed_at": row[6],
        }
        for row in rows
    ]
    return {"count": len(items), "last_email_uid": last_uid, "items": items}


def delete_processed_message(progressive_id: int) -> dict[str, Any]:
    conn = _init_db()
    try:
        cursor = conn.execute(
            "DELETE FROM processed_messages WHERE rowid = ?",
            (progressive_id,),
        )
        conn.commit()
        deleted = cursor.rowcount > 0
    finally:
        conn.close()

    return {"deleted": deleted, "id": progressive_id}


def import_new_messages(*, date_from: date | None = None, date_to: date | None = None) -> dict[str, Any]:
    now = datetime.now(UTC)
    fetch_limit = max(1, settings.mail_fetch_limit)
    default_since = date(2026, 1, 1)
    import_since = _parse_yyyy_mm_dd(settings.mail_import_since, default_since)
    sync_from = date_from or import_since
    sync_to = date_to or now.date()
    if sync_to < sync_from:
        sync_to = sync_from

    rules = _load_sender_rules()
    if not rules:
        return {
            "status": "no_rules",
            "fetch_limit": fetch_limit,
            "imported_count": 0,
            "imported": [],
        }
    if not settings.mail_username or not settings.mail_password:
        return {
            "status": "missing_mail_credentials",
            "fetch_limit": fetch_limit,
            "imported_count": 0,
            "imported": [],
        }

    conn = _init_db()
    imported: list[dict[str, Any]] = []
    latest_uid_processed: str | None = None

    try:
        last_uid = _get_last_email_uid(conn)
        first_import = not last_uid
        with imaplib.IMAP4_SSL(settings.mail_imap_host, settings.mail_imap_port) as mailbox:
            mailbox.login(settings.mail_username, settings.mail_password)
            mailbox.select("INBOX")

            next_day = sync_to + timedelta(days=1)
            status, data = mailbox.uid(
                "search",
                None,
                "SINCE",
                _to_imap_since(sync_from),
                "BEFORE",
                _to_imap_since(next_day),
            )
            if status != "OK":
                return {
                    "status": "imap_search_error",
                    "fetch_limit": fetch_limit,
                    "imported_count": 0,
                    "imported": [],
                }

            uids = [u for u in data[0].decode().split() if u]
            if first_import and settings.mail_first_import_full_scan:
                uids_to_scan = list(reversed(uids))
            else:
                uids_to_scan = list(reversed(uids[-fetch_limit:]))
            for uid in uids_to_scan:
                status, msg_data = mailbox.uid("fetch", uid, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1]
                if not raw:
                    continue

                email_message = message_from_bytes(raw)
                sender = parseaddr(email_message.get("From", ""))[1].strip().lower()
                subject = str(email_message.get("Subject", "")).strip()
                message_id = str(email_message.get("Message-ID", "")).strip() or None
                received_at = _parse_received_at(email_message, fallback=now)
                received_date = received_at.date()
                if received_date < sync_from or received_date > sync_to:
                    continue

                sender_rule = rules.get(sender)
                if not sender_rule or not sender_rule.enabled:
                    continue

                if _already_processed(conn, uid, message_id):
                    continue

                has_csv, has_pdf = _extract_flags(email_message)
                if sender_rule.require_csv and not has_csv:
                    continue
                if sender_rule.require_pdf and not has_pdf:
                    continue
                if sender_rule.supplier_id <= 0:
                    continue

                csv_text, pdf_bytes, _pdf_filename = _extract_attachments(email_message)
                records = _records_from_csv(csv_text, sender_rule.supplier_id, pdf_bytes)
                if not records:
                    continue

                intranet_results: list[dict[str, Any]] = []
                failed = False
                for record in records:
                    try:
                        intranet_results.append(_post_record_to_intranet(record))
                    except Exception as exc:  # noqa: BLE001
                        failed = True
                        intranet_results.append({"success": False, "error": str(exc)})
                        break
                if failed:
                    continue

                _mark_processed(
                    conn,
                    uid=uid,
                    message_id=message_id,
                    sender=sender,
                    subject=subject,
                    received_at=received_at,
                )

                imported.append(
                    {
                        "uid": uid,
                        "sender": sender,
                        "subject": subject,
                        "received_at": received_at.isoformat(),
                        "has_csv": has_csv,
                        "has_pdf": has_pdf,
                        "records_count": len(records),
                        "intranet_results": intranet_results,
                    }
                )
                latest_uid_processed = uid

    except (imaplib.IMAP4.error, OSError) as exc:
        return {
            "status": "imap_connection_error",
            "error": str(exc),
            "fetch_limit": fetch_limit,
            "imported_count": 0,
            "imported": [],
        }
    finally:
        conn.close()

    if latest_uid_processed:
        conn = _init_db()
        try:
            _set_last_email_uid(conn, latest_uid_processed)
        finally:
            conn.close()

    return {
        "status": "ok",
        "first_import_mode": first_import and settings.mail_first_import_full_scan,
        "mail_import_since": import_since.isoformat(),
        "sync_from": sync_from.isoformat(),
        "sync_to": sync_to.isoformat(),
        "fetch_limit": fetch_limit,
        "scanned_uids": len(uids_to_scan) if "uids_to_scan" in locals() else 0,
        "imported_count": len(imported),
        "imported": imported,
        "state_db_path": settings.mail_state_db_path,
    }


def replay_sonepar_messages(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    dry_run: bool = True,
    fetch_limit: int = 2000,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    sync_from = date_from or _parse_yyyy_mm_dd(settings.mail_import_since, date(2026, 1, 1))
    sync_to = date_to or now.date()
    if sync_to < sync_from:
        sync_to = sync_from

    rules = _load_sender_rules()
    sonepar_senders = {email for email in rules if "sonepar" in email}
    if not sonepar_senders:
        return {
            "status": "no_sonepar_rules",
            "dry_run": dry_run,
            "sync_from": sync_from.isoformat(),
            "sync_to": sync_to.isoformat(),
            "scanned_uids": 0,
            "candidate_ddt_count": 0,
            "updated_ddt_count": 0,
            "updated": [],
        }
    if not settings.mail_username or not settings.mail_password:
        return {
            "status": "missing_mail_credentials",
            "dry_run": dry_run,
            "sync_from": sync_from.isoformat(),
            "sync_to": sync_to.isoformat(),
            "scanned_uids": 0,
            "candidate_ddt_count": 0,
            "updated_ddt_count": 0,
            "updated": [],
        }

    updated: list[dict[str, Any]] = []
    scanned_uids = 0
    candidate_ddt_count = 0

    try:
        with imaplib.IMAP4_SSL(settings.mail_imap_host, settings.mail_imap_port) as mailbox:
            mailbox.login(settings.mail_username, settings.mail_password)
            mailbox.select("INBOX")

            next_day = sync_to + timedelta(days=1)
            status, data = mailbox.uid(
                "search",
                None,
                "SINCE",
                _to_imap_since(sync_from),
                "BEFORE",
                _to_imap_since(next_day),
            )
            if status != "OK":
                return {
                    "status": "imap_search_error",
                    "dry_run": dry_run,
                    "sync_from": sync_from.isoformat(),
                    "sync_to": sync_to.isoformat(),
                    "scanned_uids": 0,
                    "candidate_ddt_count": 0,
                    "updated_ddt_count": 0,
                    "updated": [],
                }

            uids = [u for u in data[0].decode().split() if u]
            uids_to_scan = list(reversed(uids[-max(1, fetch_limit) :]))
            for uid in uids_to_scan:
                scanned_uids += 1
                status, msg_data = mailbox.uid("fetch", uid, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1]
                if not raw:
                    continue

                email_message = message_from_bytes(raw)
                sender = parseaddr(email_message.get("From", ""))[1].strip().lower()
                if sender not in sonepar_senders:
                    continue

                received_at = _parse_received_at(email_message, fallback=now)
                received_date = received_at.date()
                if received_date < sync_from or received_date > sync_to:
                    continue

                sender_rule = rules.get(sender)
                if not sender_rule or sender_rule.supplier_id <= 0:
                    continue

                csv_text, pdf_bytes, _pdf_filename = _extract_attachments(email_message)
                records = _records_from_csv(csv_text, sender_rule.supplier_id, pdf_bytes)
                if not records:
                    continue

                mismatch_records = [record for record in records if bool(record.get("__has_line_mismatch"))]
                if not mismatch_records:
                    continue

                candidate_ddt_count += len(mismatch_records)
                if dry_run:
                    updated.append(
                        {
                            "uid": uid,
                            "sender": sender,
                            "received_at": received_at.isoformat(),
                            "records_count": len(mismatch_records),
                            "action": "would_update",
                        }
                    )
                    continue

                intranet_results: list[dict[str, Any]] = []
                for record in mismatch_records:
                    intranet_results.append(_post_record_to_intranet(record))
                updated.append(
                    {
                        "uid": uid,
                        "sender": sender,
                        "received_at": received_at.isoformat(),
                        "records_count": len(mismatch_records),
                        "action": "updated",
                        "intranet_results": intranet_results,
                    }
                )
    except (imaplib.IMAP4.error, OSError) as exc:
        return {
            "status": "imap_connection_error",
            "error": str(exc),
            "dry_run": dry_run,
            "sync_from": sync_from.isoformat(),
            "sync_to": sync_to.isoformat(),
            "scanned_uids": scanned_uids,
            "candidate_ddt_count": candidate_ddt_count,
            "updated_ddt_count": len(updated),
            "updated": updated,
        }

    return {
        "status": "ok",
        "dry_run": dry_run,
        "sync_from": sync_from.isoformat(),
        "sync_to": sync_to.isoformat(),
        "scanned_uids": scanned_uids,
        "candidate_ddt_count": candidate_ddt_count,
        "updated_ddt_count": len(updated),
        "updated": updated,
        "state_db_path": settings.mail_state_db_path,
    }
