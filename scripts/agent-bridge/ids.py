"""
A6 — Source unique de vérité du format d'ID agent.

Format : NNN ou NNN-NNN (ex. "300", "345-500").
Côté shell, l'équivalent est AGENT_ID_REGEX / is_valid_agent_id dans
scripts/lib.sh. Toute évolution du format se fait dans CES DEUX fichiers
uniquement.
"""
import re

AGENT_ID_PATTERN = r'[0-9]{3}(?:-[0-9]{3})?'
AGENT_ID_RE = re.compile(rf'^{AGENT_ID_PATTERN}$')


def is_valid_agent_id(value) -> bool:
    """True si value est un ID agent valide (NNN ou NNN-NNN)."""
    return bool(AGENT_ID_RE.match(str(value)))
