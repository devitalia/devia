from __future__ import annotations

import base64
import logging
import subprocess
from typing import Optional, Dict, Any

from .config import Settings

logger = logging.getLogger(__name__)


def synthesize_reply(settings: Settings, text: str) -> Optional[Dict[str, Any]]:
    """
    Genera la versione audio (WAV, base64) di una risposta testuale usando
    Piper con modelli italiani (es. it_IT-paola-medium).
    In caso di errore restituisce None senza interrompere il flusso della chat.
    """
    if not text or not settings.tts_enabled:
        return None

    model_path = (settings.tts_model_path or "").strip()
    if not model_path:
        logger.warning("TTS abilitato ma DEVIA_TTS_MODEL_PATH non è configurato")
        return None

    try:
        proc = subprocess.run(
            [
                "python",
                "-m",
                "piper",
                "--model",
                model_path,
                "--output_file",
                "-",
            ],
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except FileNotFoundError:
        logger.warning("Comando 'python -m piper' non trovato: TTS disabilitato")
        return None
    except subprocess.CalledProcessError as e:  # pragma: no cover
        logger.warning(
            "Piper TTS ha restituito un errore (exit %s): %s",
            e.returncode,
            (e.stderr or b"").decode("utf-8", errors="ignore").strip(),
        )
        return None
    except Exception as e:  # pragma: no cover
        logger.warning("Errore inaspettato durante la generazione audio TTS: %s", e)
        return None

    wav_bytes = proc.stdout or b""
    if not wav_bytes:
        logger.warning("Piper TTS non ha prodotto alcun output audio")
        return None

    b64 = base64.b64encode(wav_bytes).decode("ascii")
    return {
        "mime": "audio/wav",
        "base64": b64,
    }
