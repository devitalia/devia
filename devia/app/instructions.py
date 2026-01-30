from pathlib import Path

from .config import Settings


def load_instructions(settings: Settings) -> dict:
    base = Path(settings.instructions_path)
    project_md = (base / "project.md").read_text(encoding="utf-8") if (base / "project.md").exists() else ""
    policy_md = (base / "policy.md").read_text(encoding="utf-8") if (base / "policy.md").exists() else ""

    return {
        "project_md": project_md,
        "policy_md": policy_md,
    }
