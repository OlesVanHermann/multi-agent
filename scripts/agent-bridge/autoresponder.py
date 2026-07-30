#!/usr/bin/env python3
"""Classification et déduplication des dialogues interactifs des CLI.

Le bridge doit pouvoir répondre même lorsqu'aucun navigateur n'est connecté.
Ce module reste volontairement indépendant de tmux : il classe un viewport
déjà capturé et borne les tentatives. L'envoi des touches reste dans agent.py,
sous le verrou qui protège le TUI.
"""

from dataclasses import dataclass
import hashlib
import os
import re
import threading
import time


_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_NUMBERED_OPTION_RE = re.compile(
    r"^\s*(?:(?P<prefix>[^\w\s])\s*)?(?P<number>[0-9]+)[.):]\s*(?P<label>.*)$"
)

# Politique de sécurité commune à TOUS les moteurs — volontairement hors des
# fichiers de marqueurs : ce ne sont pas des chaînes d'UI de CLI, et cette
# frontière ne doit pas pouvoir être affaiblie en éditant un marqueur.
#
# Règle opérateur : jamais `rm` & co, toujours `mv` vers removed/ (safe_rm).
# Le problème n'est pas l'auto-validation, c'est la commande : un déplacement
# est rattrapable, une suppression ne l'est pas. Tant qu'un motif irréversible
# est visible dans le dialogue actif, aucune touche ne part et l'humain décide.
_IRREVERSIBLE_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\brm\b", r"\brmdir\b", r"\bunlink\b", r"\bshred\b", r"\btruncate\b",
    r"\bmkfs\b", r"\bdd\s+if=", r">\s*/dev/sd",
    r"\bDROP\s+(TABLE|DATABASE)\b", r"\bDELETE\s+FROM\b",
    r"\bgit\s+(clean|reset\s+--hard)\b", r"\bgit\s+push\b.*--force",
    r"\bfind\b.*-delete", r"\bkill\s+-9\b", r"\bchmod\s+-R\b",
    r"\bcurl\b[^\n]*\|\s*(ba)?sh\b", r"\bwget\b[^\n]*\|\s*(ba)?sh\b",
))


def irreversible_marker(text):
    """Retourne le motif irréversible trouvé dans le texte, sinon ''.

    Garde-fou terminal appliqué à TOUS les types de dialogue, y compris une
    option explicitement « recommandée » : le mot « recommandé » n'a jamais
    accordé d'autorité destructive.
    """
    for pattern in _IRREVERSIBLE_PATTERNS:
        if pattern.search(str(text or "")):
            return pattern.pattern
    return ""


@dataclass(frozen=True)
class AutoResponseDecision:
    """Réponse sûre à un dialogue actif, sans reprendre son contenu en log."""

    kind: str
    keys: tuple
    fingerprint: str


def _clean_lines(pane_text, tail_lines):
    text = _ANSI_RE.sub("", str(pane_text or "")).replace("\r", "")
    lines = text.splitlines()
    # capture-pane rend la hauteur complète du viewport : un dialogue court
    # peut être suivi de dizaines de rangs vides. Ils ne doivent pas pousser la
    # modale hors de la fenêtre active.
    while lines and not lines[-1].strip():
        lines.pop()
    return [line.rstrip() for line in lines[-max(1, int(tail_lines)):]]


def _contains_any(text, values):
    return next((str(value) for value in values if str(value) in text), None)


def _fingerprint(kind, *parts):
    signature = "\n".join(
        [kind] + [re.sub(r"\s+", " ", str(part)).strip() for part in parts]
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20]


def _selected_option_block(lines, config, waiting_marker):
    """Retourne contexte + option numérotée sélectionnée, sinon None."""

    footer_indexes = [
        index for index, line in enumerate(lines) if waiting_marker in line
    ]
    if not footer_indexes:
        return None
    footer_index = footer_indexes[-1]
    prefixes = tuple(str(item) for item in config.get("selected_prefixes", []))
    if not prefixes:
        return None

    selected = []
    for index, line in enumerate(lines[:footer_index]):
        stripped = line.lstrip()
        if not stripped.startswith(prefixes):
            continue
        remainder = stripped[1:].lstrip()
        if re.match(r"^[0-9]+[.):]\s+", remainder):
            selected.append(index)

    # Plusieurs curseurs numérotés dans la zone active rendent le choix ambigu.
    if len(selected) != 1:
        return None

    start = selected[0]
    block = [lines[start]]
    for line in lines[start + 1:footer_index]:
        match = _NUMBERED_OPTION_RE.match(line)
        if match and match.group("number"):
            break
        block.append(line)
    normalized = "\n".join(block)
    # Deux questions différentes peuvent proposer le même libellé. Inclure la
    # ligne métier précédente stabilise l'empreinte sans absorber le footer.
    question = ""
    for line in reversed(lines[:start]):
        candidate = line.strip()
        if not candidate or _NUMBERED_OPTION_RE.match(line):
            continue
        question = candidate
        break
    return "\n".join((question, normalized))


def _selected_recommended_block(lines, config, waiting_marker):
    block = _selected_option_block(lines, config, waiting_marker)
    recommended = str(config.get("recommended_marker", ""))
    return block if block and recommended and recommended in block else None


def classify_active_dialog(pane_text, pane_command, markers):
    """Classe uniquement un dialogue complet situé dans le bas du viewport.

    Aucun marqueur isolé ne suffit. Le processus courant doit être celui du
    moteur, l'option attendue doit être visible et les AskUserQuestion ne sont
    acceptées que si l'option *actuellement sélectionnée* est recommandée.
    """

    process = os.path.basename(str(pane_command or "")).lower()
    expected = {
        os.path.basename(str(item)).lower()
        for item in markers.get("process_names", [])
    }
    if not process or process not in expected:
        return None

    config = markers.get("auto_response") or {}
    if not config.get("enabled", True):
        return None
    lines = _clean_lines(pane_text, config.get("tail_lines", 30))
    active = "\n".join(lines)
    # Garde-fou terminal, avant toute classification : tant qu'un motif
    # irréversible est visible dans le dialogue actif, aucune touche n'est
    # calculée — approbation, sondage ou option « recommandée » confondus.
    if irreversible_marker(active):
        return None
    waiting_marker = str(markers.get("waiting_select", ""))

    survey_marker = str(markers.get("survey", ""))
    survey_option = _contains_any(
        active, config.get("survey_option_patterns", []))
    if survey_marker and survey_marker in active and survey_option:
        keys = tuple(str(key) for key in config.get("survey_keys", ()))
        if keys:
            return AutoResponseDecision(
                "survey", keys,
                _fingerprint("survey", survey_marker, survey_option))

    approval_marker = str(markers.get("approval", ""))
    approval_option = _contains_any(
        active, config.get("approval_option_patterns", []))
    if (approval_marker and approval_marker in active and approval_option
            and waiting_marker and waiting_marker in active):
        keys = tuple(str(key) for key in config.get("approval_keys", ()))
        # Tous les éléments d'autorité doivent appartenir au même bloc courant.
        # Sans ce lien structurel, un ancien « Would you like to proceed? /
        # 1. Yes » encore visible pourrait autoriser un menu différent situé
        # plus bas dans le viewport. Même lorsque Claude reçoit explicitement
        # « 1 Enter », on exige donc que l'option positive soit sélectionnée et
        # que sa question porte le marqueur d'approbation.
        selected_approval = _selected_option_block(
            lines, config, waiting_marker)
        if (not selected_approval
                or approval_marker not in selected_approval
                or approval_option not in selected_approval):
            keys = ()
        if keys:
            return AutoResponseDecision(
                "approval", keys,
                _fingerprint("approval", approval_marker, approval_option))

    selected = _selected_recommended_block(
        lines, config, waiting_marker) if waiting_marker else None
    if selected:
        keys = tuple(str(key) for key in config.get("recommended_keys", ()))
        if keys:
            return AutoResponseDecision(
                "ask_user_recommended", keys,
                _fingerprint("ask_user_recommended", selected))
    return None


class AutoResponder:
    """Réserve au plus ``max_attempts`` envois pour un même dialogue."""

    def __init__(self, cooldown_seconds=15, max_attempts=3, clock=None):
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._fingerprint = None
        self._attempts = 0
        self._last_attempt_at = None
        self._last_result = None

    @property
    def attempts(self):
        with self._lock:
            return self._attempts

    def observe(self, decision):
        """Réserve atomiquement une tentative si cooldown et plafond l'autorisent."""

        if decision is None:
            self.reset_when_absent()
            return False
        now = self._clock()
        with self._lock:
            if decision.fingerprint != self._fingerprint:
                self._fingerprint = decision.fingerprint
                self._attempts = 0
                self._last_attempt_at = None
                self._last_result = None
            if self._last_result == "applied":
                return False
            if self._attempts >= self.max_attempts:
                return False
            if (self._last_attempt_at is not None
                    and now - self._last_attempt_at < self.cooldown_seconds):
                return False
            # Réservation avant l'I/O : deux scanners ne peuvent pas envoyer.
            self._attempts += 1
            self._last_attempt_at = now
            self._last_result = "reserved"
            return True

    def mark_applied(self, decision):
        with self._lock:
            if decision and decision.fingerprint == self._fingerprint:
                self._last_result = "applied"

    def mark_failed(self, decision):
        with self._lock:
            if decision and decision.fingerprint == self._fingerprint:
                self._last_result = "failed"
                # La tentative tmux a échoué : le cooldown empêche une boucle
                # CPU serrée, puis une nouvelle tentative reste possible.

    def reset_when_absent(self):
        """Réarme seulement après disparition du dialogue du viewport actif."""

        with self._lock:
            self._fingerprint = None
            self._attempts = 0
            self._last_attempt_at = None
            self._last_result = None
