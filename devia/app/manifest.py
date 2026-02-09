"""
Project Manifest: mappa mentale in pochi token (stack, domini, indice tabelle, operazioni).
Usato in cima al system prompt per dare al modello una visione chiara senza dump di codice.
"""
from __future__ import annotations

# Mapping nome tabella -> label breve (opzionale; estendibile da config/file)
_TABLE_LABELS: dict[str, str] = {
    "users": "utenti",
    "user": "utente",
    "presenze": "presenze",
    "teams": "team",
    "ferie": "ferie",
    "permessi": "permessi",
    "migrations": "migrazioni",
}


def _table_index_line(table_names: list[str]) -> str:
    """Elenco compatto tabelle con eventuale label."""
    parts = []
    for t in sorted(table_names):
        label = _TABLE_LABELS.get(t, t)
        if label != t:
            parts.append(f"{t} ({label})")
        else:
            parts.append(t)
    return ", ".join(parts) if parts else "(nessuna)"


def _extract_domains(project_md: str) -> list[str]:
    """Estrae domini da project.md: righe che iniziano con 'domains:' o '- dominio' o da testo."""
    domains: list[str] = []
    for line in project_md.splitlines():
        line = line.strip()
        if line.startswith("domains:") or line.startswith("- domains:"):
            continue
        if line.startswith("- ") and len(line) > 2:
            word = line[2:].strip().split()[0] if line[2:].strip() else ""
            if word and not word.startswith("#") and word not in ("uso", "procedure", "spiegazioni", "Fonte"):
                # Evita bullet generici
                if word in ("auth", "billing", "users", "presenze", "ferie", "permessi", "analytics", "intranet"):
                    domains.append(word)
    if not domains:
        domains = ["auth", "users", "presenze", "ferie", "permessi"]
    return domains


def build_project_manifest(
    db_schema: str | None,
    project_md: str,
    table_names: list[str],
    operations_md: str = "",
) -> str:
    """
    Costruisce la stringa del Project Manifest (pochi token).
    Input: schema (opzionale, per lunghezza), project.md, elenco nomi tabelle, operations.md opzionale.
    """
    stack = "Laravel + MySQL"
    domains = _extract_domains(project_md)
    tables_line = _table_index_line(table_names)

    lines = [
        "## Project Manifest (mappa mentale)",
        "",
        "project:",
        f"  stack: {stack}",
        f"  domains: {', '.join(domains)}",
        f"  tables: {tables_line}",
        "  rules:",
        "    - non inventare dati; usa una query SQL quando servono dati",
        "    - rispondi in italiano",
        "",
    ]

    if operations_md and operations_md.strip():
        lines.extend([
            "  operations (query hints):",
            "",
            operations_md.strip(),
            "",
        ])

    return "\n".join(lines)
