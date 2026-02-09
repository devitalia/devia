from pathlib import Path

from .config import Settings


def load_instructions(settings: Settings) -> dict:
    base = Path(settings.instructions_path)
    project_md = (base / "project.md").read_text(encoding="utf-8") if (base / "project.md").exists() else ""
    policy_md = (base / "policy.md").read_text(encoding="utf-8") if (base / "policy.md").exists() else ""
    operations_md = (base / "operations.md").read_text(encoding="utf-8") if (base / "operations.md").exists() else ""

    return {
        "project_md": project_md,
        "policy_md": policy_md,
        "operations_md": operations_md,
    }


def load_repo_code(settings: Settings) -> str:
    """
    Carica codice intranet dal repo (solo modelli Laravel) per far costruire le query al LLM.
    Lo schema DB reale è già iniettato separatamente; i Models danno tabelle, relazioni, uso logico.
    Default repo_max_chars=0: nessun codice in prompt; le risposte si cercano con query sul DB.
    """
    if not settings.repo_path or settings.repo_max_chars <= 0:
        return ""
    root = Path(settings.repo_path)
    if not root.is_dir():
        return ""
    max_chars = settings.repo_max_chars  # 0 = nessun codice in prompt
    out: list[str] = []
    total = 0
    # Includi anche controller e routes per dare all'IA visibilità sul flusso applicativo
    globs = [
        "app/Models/*.php",
        "app/Http/Controllers/*.php",
        "routes/*.php",
    ]
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(root)
            block = f"## file: {rel}\n{text}\n"
            if total + len(block) > max_chars:
                # Tronca l'ultimo file se necessario
                take = max(0, max_chars - total - 80)
                if take > 0:
                    out.append(f"## file: {rel}\n{text[:take]}\n... (truncated)\n")
                break
            out.append(block)
            total += len(block)
        if total >= max_chars:
            break
    return "".join(out) if out else ""


def list_repo_files(settings: Settings) -> list[str]:
    """Elenco dei file PHP caricati dal repo (app/Models)."""
    if not settings.repo_path:
        return []
    root = Path(settings.repo_path)
    if not root.is_dir():
        return []
    out: list[str] = []
    patterns = [
        "app/Models/*.php",
        "app/Http/Controllers/*.php",
        "routes/*.php",
    ]
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                out.append(str(path.relative_to(root)))
    return out
