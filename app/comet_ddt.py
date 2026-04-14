from __future__ import annotations

import base64
import json
import re
import sqlite3
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from playwright.sync_api import sync_playwright

from app.config import settings


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = conn.execute(f"PRAGMA table_info({table})").fetchall()
    names = {row[1] for row in existing}
    if column not in names:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _init_db() -> sqlite3.Connection:
    db_path = Path(settings.mail_state_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS comet_ddt_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_key TEXT NOT NULL UNIQUE,
            numero_riferimento TEXT,
            riferimento_cliente TEXT,
            numero_documento TEXT,
            data_documento TEXT,
            tipo_documento TEXT,
            indirizzo_destinazione TEXT,
            numero_ordine_interno TEXT,
            totale_documento TEXT,
            csv_url TEXT,
            pdf_url TEXT,
            csv_file_path TEXT,
            pdf_file_path TEXT,
            intranet_payload_json TEXT,
            row_payload TEXT NOT NULL,
            imported_at TEXT NOT NULL
        )
        """
    )
    _ensure_column(conn, "comet_ddt_imports", "intranet_payload_json", "TEXT")
    conn.commit()
    return conn


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("_") or "unknown"


def _parse_yyyy_mm_dd(value: str, fallback: date) -> date:
    raw = (value or "").strip()
    if not raw:
        return fallback
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return fallback


def _parse_dd_mm_yyyy(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _extract_document_key(row: dict[str, Any]) -> str:
    for key in ("csv_url", "pdf_url"):
        url = str(row.get(key) or "")
        match = re.search(r"/download/ddt-(?:csv|pdf)/([^/]+)/", url)
        if match:
            return match.group(1)
    text_key = f"{row.get('numero_riferimento', '')}-{row.get('numero_documento', '')}"
    return _slug(text_key)


def _extract_rows_from_page(page: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = page.eval_on_selector_all(
        "table tbody tr",
        """
        (trs) => trs.map((tr) => {
          const cells = Array.from(tr.querySelectorAll("td")).map((td) =>
            (td.innerText || "").replace(/\\s+/g, " ").trim()
          );
          const csvLink = tr.querySelector('a[href*="/download/ddt-csv/"]');
          const pdfLink = tr.querySelector('a[href*="/download/ddt-pdf/"]');
          const detailBtn = tr.querySelector('button.js-view-detail');
          return {
            cells,
            csv_url: csvLink ? csvLink.href : null,
            pdf_url: pdfLink ? pdfLink.href : null,
            detail_number: detailBtn ? (detailBtn.getAttribute('data-number') || '') : ''
          };
        })
        """,
    )

    parsed: list[dict[str, Any]] = []
    for row in rows:
        cells = row.get("cells") or []
        csv_url = row.get("csv_url")
        pdf_url = row.get("pdf_url")
        if not csv_url and not pdf_url:
            continue

        while len(cells) < 8:
            cells.append("")

        parsed.append(
            {
                "numero_riferimento": cells[0],
                "riferimento_cliente": cells[1],
                "numero_documento": cells[2],
                "data_documento": cells[3],
                "tipo_documento": cells[4],
                "indirizzo_destinazione": cells[5],
                "numero_ordine_interno": cells[6],
                "totale_documento": cells[7],
                "csv_url": csv_url,
                "pdf_url": pdf_url,
                "detail_number": (row.get("detail_number") or "").strip(),
                "raw_cells": cells,
            }
        )
    return parsed


def _extract_detail_lines_from_view(page: Any) -> dict[str, Any]:
    detail_rows: list[list[str]] = page.eval_on_selector_all(
        ".modal.show table tbody tr, .modal table.table-hover tbody tr, table.table-hover.table-ordine tbody tr",
        """
        (trs) => trs.map((tr) =>
          Array.from(tr.querySelectorAll("td")).map((td) =>
            (td.innerText || "").replace(/\\s+/g, " ").trim()
          )
        )
        """,
    )

    lines: list[dict[str, str]] = []
    total = ""
    for cols in detail_rows:
        if not cols:
            continue
        first = (cols[0] or "").strip().upper()
        if first.startswith("TOTALE"):
            total = cols[1].strip() if len(cols) > 1 else ""
            continue
        if len(cols) < 9:
            continue
        lines.append(
            {
                "n": cols[0],
                "codice_interno": cols[1],
                "codice_articolo": cols[2],
                "marchio": cols[3],
                "descrizione": cols[4],
                "prezzo_unitario": cols[5],
                "quantita": cols[6],
                "codice_iva": cols[7],
                "importo": cols[8],
            }
        )
    return {"lines": lines, "total": total}


def _open_detail_modal(page: Any, detail_number: str, fallback_index: int) -> None:
    normalized = " ".join(detail_number.split()).strip()
    candidates = []
    if normalized:
        candidates.extend(
            [
                f'button.js-view-detail[data-number="{normalized}"]',
                f'button.js-view-detail[data-number*="{normalized}"]',
            ]
        )

    for selector in candidates:
        locator = page.locator(selector)
        if locator.count() > 0:
            locator.first.click(timeout=4000)
            return

    page.locator("button.js-view-detail").nth(fallback_index).click(timeout=4000)


def _build_authenticated_session(cookies: list[dict[str, Any]], user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    for cookie in cookies:
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    return session


def _download_file(session: requests.Session, url: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = session.get(url, timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return str(destination)


def _download_text(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def _fetch_comet_ddt_html(session: requests.Session, from_date: date, to_date: date) -> str:
    search_url = urljoin(settings.comet_base_url, "/ajax/order-search")
    payload = {
        "op": "search",
        "kind": "ddt",
        "from": from_date.strftime("%d/%m/%Y"),
        "to": to_date.strftime("%d/%m/%Y"),
        "evasi": "true",
        "u": str(int(time.time() * 1000)),
    }
    response = session.post(search_url, data=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    html = str(data.get("html") or "")
    if not html:
        raise ValueError("empty_comet_search_html")
    return html


def _extract_detail_from_csv_text(csv_text: str) -> tuple[list[dict[str, str]], str]:
    lines: list[dict[str, str]] = []
    detail_total = ""
    raw_lines = [ln.strip() for ln in csv_text.splitlines() if ln.strip()]
    if not raw_lines:
        return lines, detail_total

    for idx, line in enumerate(raw_lines):
        cols = [c.strip() for c in line.split(";")]
        if idx == 0:
            # COMET first row is document header; column 7 is document total.
            if len(cols) > 6:
                detail_total = cols[6]
            continue

        if len(cols) < 8:
            continue

        lines.append(
            {
                "n": str(idx),
                "codice_interno": cols[3],
                "codice_articolo": cols[2],
                "marchio": cols[0],
                "descrizione": cols[4],
                "prezzo_unitario": cols[5],
                "quantita": cols[6],
                "codice_iva": "",
                "importo": cols[7],
            }
        )

    return lines, detail_total


def _apply_comet_date_filter(page: Any, from_date: date, to_date: date) -> bool:
    from_str = from_date.strftime("%d/%m/%Y")
    to_str = to_date.strftime("%d/%m/%Y")

    def _fill_first(locator: Any, value: str) -> bool:
        count = locator.count()
        if count <= 0:
            return False
        for idx in range(count):
            candidate = locator.nth(idx)
            try:
                candidate.fill(value, timeout=2000)
                return True
            except Exception:  # noqa: BLE001
                continue
        return False

    # 0) COMET usa principalmente un date-range unico (es. "07/04/2026 - 13/04/2026").
    range_locator = page.locator("input#date-range, input[name='date-range'], input.input-date-range")
    if range_locator.count() > 0:
        range_value = f"{from_str} - {to_str}"
        try:
            target = range_locator.first
            target.fill(range_value, timeout=2000)
            target.dispatch_event("input")
            target.dispatch_event("change")
            page.evaluate(
                """(value) => {
                    const input = document.querySelector('#date-range') ||
                                  document.querySelector('input[name=\"date-range\"]') ||
                                  document.querySelector('input.input-date-range');
                    if (input) {
                        input.value = value;
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }""",
                range_value,
            )
            return True
        except Exception:  # noqa: BLE001
            pass

    # 1) Tentativo su campi espliciti "Dal"/"Al" legati a label.
    filled_from = _fill_first(page.get_by_label("Dal", exact=False), from_str)
    filled_to = _fill_first(page.get_by_label("Al", exact=False), to_str)
    if filled_from:
        return True

    # 2) Tentativo su attributi tipici (name/id/placeholder/class).
    selectors_from = [
        "input[name*='data'][name*='da']",
        "input[id*='data'][id*='da']",
        "input[placeholder*='dal' i]",
        "input[class*='dal' i]",
        "input[name*='from' i]",
        "input[id*='from' i]",
    ]
    selectors_to = [
        "input[name*='data'][name$='a']",
        "input[id*='data'][id$='a']",
        "input[placeholder*='al' i]",
        "input[class*='al' i]",
        "input[name*='to' i]",
        "input[id*='to' i]",
    ]

    for selector in selectors_from:
        if _fill_first(page.locator(selector), from_str):
            filled_from = True
            break
    for selector in selectors_to:
        if _fill_first(page.locator(selector), to_str):
            filled_to = True
            break

    if filled_from:
        return True

    # 3) Fallback finale: prende i primi input "date/data" e imposta dal/al.
    generic_date_inputs = page.locator(
        "input[type='date'], input[placeholder*='data' i], input[name*='date' i], input[id*='date' i]"
    )
    if generic_date_inputs.count() >= 1:
        try:
            generic_date_inputs.first.fill(from_str, timeout=2000)
            filled_from = True
            if generic_date_inputs.count() > 1 and not filled_to:
                generic_date_inputs.nth(1).fill(to_str, timeout=2000)
        except Exception:  # noqa: BLE001
            pass

    return filled_from


def _post_to_intranet(payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.intranet_api_url:
        return

    testata = payload.get("testata") or {}
    righe = payload.get("righe") or []
    supplier_raw = str(testata.get("codice_fornitore") or "").strip()
    try:
        supplier_id = int(supplier_raw)
    except ValueError:
        supplier_id = 0

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    token = (settings.intranet_api_token or "").strip()

    body = {
        "token": token,
        "supplier_id": supplier_id,
        "testata": {
            "numero_riferimento": testata.get("numero_riferimento", ""),
            "riferimento_cliente": testata.get("riferimento_cliente", ""),
            "numero_documento": testata.get("numero_documento", ""),
            "data_documento": testata.get("data_documento", ""),
            "tipo_documento": testata.get("tipo_documento", ""),
            "indirizzo_destinazione": testata.get("indirizzo_destinazione", ""),
            "numero_ordine_interno": testata.get("numero_ordine_interno", ""),
            "totale_documento": testata.get("totale_documento", ""),
            "totale_righe_dettaglio": testata.get("totale_righe_dettaglio", ""),
            "pdf_url": testata.get("pdf_url", ""),
            "pdf_filename": testata.get("pdf_filename", ""),
            "pdf_base64": testata.get("pdf_base64", ""),
        },
        "righe": righe,
    }

    response = requests.post(
        settings.intranet_api_url,
        json=body,
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        return {"raw_response": response.text}


def sync_comet_ddt(*, date_from: date | None = None, date_to: date | None = None) -> dict[str, Any]:
    if not settings.comet_username or not settings.comet_password:
        return {"status": "missing_comet_credentials", "imported_count": 0, "skipped_count": 0}

    login_url = urljoin(settings.comet_base_url, settings.comet_login_path)
    ddt_url = urljoin(settings.comet_base_url, settings.comet_ddt_path)
    download_root = Path(settings.comet_download_dir)
    pdf_dir = download_root / "pdf"

    supplier_code = (settings.comet_supplier_code or settings.comet_username or "").strip()
    default_since = date(2026, 1, 1)
    import_since = _parse_yyyy_mm_dd(settings.comet_import_since, default_since)
    sync_from = date_from or import_since
    sync_to = date_to or datetime.now().date()
    if sync_to < sync_from:
        sync_to = sync_from

    conn = _init_db()
    imported: list[dict[str, Any]] = []
    skipped = 0
    errors: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    try:
        existing_keys = {
            row[0] for row in conn.execute("SELECT document_key FROM comet_ddt_imports").fetchall()
        }

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=settings.comet_headless)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            try:
                page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
                try:
                    page.locator("button:has-text('Accetta')").first.click(timeout=1500)
                except Exception:
                    pass

                page.locator("input[placeholder='123456789']").fill(settings.comet_username)
                page.locator("input[type='password']").fill(settings.comet_password)
                page.locator("button:has-text('Accedi')").first.click()
                page.wait_for_timeout(2000)

                user_agent = page.evaluate("() => navigator.userAgent")
                session = _build_authenticated_session(context.cookies(), user_agent)
                page.goto(ddt_url, wait_until="domcontentloaded", timeout=60000)

                comet_filter_applied = False
                try:
                    search_html = _fetch_comet_ddt_html(session, sync_from, sync_to)
                    page.set_content(search_html, wait_until="domcontentloaded")
                    comet_filter_applied = True
                except Exception:  # noqa: BLE001
                    # Fallback UI: keeps compatibility if ajax endpoint changes.
                    comet_filter_applied = _apply_comet_date_filter(page, sync_from, sync_to)
                    page.locator("button:has-text('Cerca')").first.click(timeout=10000)
                    page.wait_for_timeout(2500)

                raw_rows = _extract_rows_from_page(page)
                rows = []
                for row in raw_rows:
                    for url_key in ("csv_url", "pdf_url"):
                        url_value = str(row.get(url_key) or "").strip()
                        if url_value:
                            row[url_key] = urljoin(settings.comet_base_url, url_value)
                    row_date = _parse_dd_mm_yyyy(str(row.get("data_documento", "")))
                    if row_date and (row_date < sync_from or row_date > sync_to):
                        continue
                    rows.append(row)
            finally:
                browser.close()

        for row in rows:
            document_key = _extract_document_key(row)
            if document_key in existing_keys:
                skipped += 1
                continue

            csv_url = row.get("csv_url") or ""
            pdf_url = row.get("pdf_url") or ""
            date_slug = _slug(str(row.get("data_documento") or datetime.now(UTC).date().isoformat()))
            detail_lines: list[dict[str, str]] = []
            detail_total = row.get("totale_documento", "")
            if csv_url:
                try:
                    csv_text = _download_text(session, csv_url)
                    detail_lines, csv_total = _extract_detail_from_csv_text(csv_text)
                    if csv_total:
                        detail_total = csv_total
                except Exception:  # noqa: BLE001
                    detail_lines = []
            intranet_payload = {
                "testata": {
                    "document_key": document_key,
                    "codice_fornitore": supplier_code,
                    "numero_riferimento": row.get("numero_riferimento", ""),
                    "riferimento_cliente": row.get("riferimento_cliente", ""),
                    "numero_documento": row.get("numero_documento", ""),
                    "data_documento": row.get("data_documento", ""),
                    "tipo_documento": row.get("tipo_documento", ""),
                    "indirizzo_destinazione": row.get("indirizzo_destinazione", ""),
                    "numero_ordine_interno": row.get("numero_ordine_interno", ""),
                    "totale_documento": row.get("totale_documento", ""),
                    "totale_righe_dettaglio": detail_total,
                    "pdf_url": pdf_url,
                    "pdf_filename": "",
                    "pdf_base64": "",
                },
                "righe": detail_lines,
            }

            csv_path = ""
            pdf_path = ""
            try:
                if pdf_url:
                    pdf_path = _download_file(
                        session,
                        pdf_url,
                        pdf_dir / f"{_slug(document_key)}_{date_slug}.pdf",
                    )
                    intranet_payload["testata"]["pdf_filename"] = Path(pdf_path).name
                    if settings.intranet_send_pdf_base64:
                        pdf_bytes = Path(pdf_path).read_bytes()
                        intranet_payload["testata"]["pdf_base64"] = base64.b64encode(
                            pdf_bytes
                        ).decode("ascii")
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "document_key": document_key,
                        "error": f"download_failed: {exc}",
                    }
                )
                continue

            try:
                intranet_result = _post_to_intranet(intranet_payload)
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "document_key": document_key,
                        "error": f"intranet_post_failed: {exc}",
                    }
                )
                continue

            conn.execute(
                """
                INSERT INTO comet_ddt_imports (
                    document_key,
                    numero_riferimento,
                    riferimento_cliente,
                    numero_documento,
                    data_documento,
                    tipo_documento,
                    indirizzo_destinazione,
                    numero_ordine_interno,
                    totale_documento,
                    csv_url,
                    pdf_url,
                    csv_file_path,
                    pdf_file_path,
                    intranet_payload_json,
                    row_payload,
                    imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_key,
                    row.get("numero_riferimento", ""),
                    row.get("riferimento_cliente", ""),
                    row.get("numero_documento", ""),
                    row.get("data_documento", ""),
                    row.get("tipo_documento", ""),
                    row.get("indirizzo_destinazione", ""),
                    row.get("numero_ordine_interno", ""),
                    row.get("totale_documento", ""),
                    csv_url,
                    pdf_url,
                    csv_path,
                    pdf_path,
                    json.dumps(intranet_payload, ensure_ascii=True),
                    json.dumps(row, ensure_ascii=True),
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
            existing_keys.add(document_key)
            imported.append(
                {
                    "document_key": document_key,
                    "numero_documento": row.get("numero_documento", ""),
                    "data_documento": row.get("data_documento", ""),
                    "righe_count": len(detail_lines),
                    "csv_file_path": csv_path,
                    "pdf_file_path": pdf_path,
                    "intranet_payload": intranet_payload,
                    "intranet_result": intranet_result,
                }
            )
    finally:
        conn.close()

    return {
        "status": "ok",
        "comet_import_since": import_since.isoformat(),
        "sync_from": sync_from.isoformat(),
        "sync_to": sync_to.isoformat(),
        "comet_filter_applied": comet_filter_applied if "comet_filter_applied" in locals() else False,
        "scanned_count": len(rows),
        "imported_count": len(imported),
        "skipped_count": skipped,
        "errors_count": len(errors),
        "imported": imported,
        "errors": errors,
        "download_dir": str(download_root),
        "state_db_path": settings.mail_state_db_path,
    }


def list_comet_ddt_imports() -> dict[str, Any]:
    conn = _init_db()
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                document_key,
                numero_riferimento,
                riferimento_cliente,
                numero_documento,
                data_documento,
                tipo_documento,
                indirizzo_destinazione,
                numero_ordine_interno,
                totale_documento,
                csv_url,
                pdf_url,
                csv_file_path,
                pdf_file_path,
                intranet_payload_json,
                imported_at
            FROM comet_ddt_imports
            ORDER BY id DESC
            """
        ).fetchall()
    finally:
        conn.close()

    items = [
        {
            "id": row[0],
            "document_key": row[1],
            "numero_riferimento": row[2],
            "riferimento_cliente": row[3],
            "numero_documento": row[4],
            "data_documento": row[5],
            "tipo_documento": row[6],
            "indirizzo_destinazione": row[7],
            "numero_ordine_interno": row[8],
            "totale_documento": row[9],
            "csv_url": row[10],
            "pdf_url": row[11],
            "csv_file_path": row[12],
            "pdf_file_path": row[13],
            "intranet_payload": json.loads(row[14]) if row[14] else None,
            "imported_at": row[15],
        }
        for row in rows
    ]
    return {"count": len(items), "items": items}


def delete_comet_ddt_import(progressive_id: int) -> dict[str, Any]:
    conn = _init_db()
    try:
        row = conn.execute(
            "SELECT csv_file_path, pdf_file_path FROM comet_ddt_imports WHERE id = ? LIMIT 1",
            (progressive_id,),
        ).fetchone()
        cursor = conn.execute(
            "DELETE FROM comet_ddt_imports WHERE id = ?",
            (progressive_id,),
        )
        conn.commit()
        deleted = cursor.rowcount > 0
    finally:
        conn.close()

    if deleted and row:
        csv_path, pdf_path = row
        for file_path in (csv_path, pdf_path):
            if file_path:
                path = Path(file_path)
                if path.exists():
                    path.unlink()

    return {"deleted": deleted, "id": progressive_id}
