"""Modèles Pydantic des requêtes/réponses API (B1)."""

from typing import Optional

from pydantic import BaseModel


class AgentStatus(BaseModel):
    id: str
    status: str = "unknown"
    last_seen: int = 0
    queue_size: int = 0
    tasks_completed: int = 0
    mode: str = "unknown"


class SendMessage(BaseModel):
    message: str
    from_agent: str = "web"


class LoginModelUpdate(BaseModel):
    agent_id: str      # "300" or "default"
    type: str          # "login" or "model"; engine is inferred from model
    value: str         # "claude2a", "gpt-5-6-sol", "codex"... or "" to remove override
    confirm_global: bool = False


class AgentEngineUpdate(BaseModel):
    """E1 — Bascule ATOMIQUE moteur + modèle (+ profil) d'un agent.

    Indispensable : le garde-fou de compatibilité rend toute bascule en deux
    POST séparés impossible (chaque étape isolée est incohérente, donc rejetée).
    """
    agent_id: str                    # "301" ou "default"
    cli: str                         # "claude" | "codex"
    model: str                       # nom de fichier .model (ex. "gpt-5-6-sol")
    login: Optional[str] = None      # nom de fichier .login ; None = inchangé


class EffortUpdate(BaseModel):
    agent_id: str      # "300" or "default"
    level: str         # "L", "M", "H", or "" (remove override)
    confirm_global: bool = False


class PanelConfigUpdate(BaseModel):
    agent_id: str      # "301", "500", etc.
    panel: str         # "control", "agent", or "" to remove override


class CrontabCreate(BaseModel):
    agent_id: str      # "300", "309", etc.
    period: int        # 10, 30, 60, or 120
    prompt: str        # prompt content


class CrontabUpdate(BaseModel):
    agent_id: str
    period: int
    prompt: Optional[str] = None
    action: Optional[str] = None  # "suspend" or "resume"


class CrontabDelete(BaseModel):
    agent_id: str
    period: int


class UpdateInput(BaseModel):
    text: str
    previous: str = ""
    submit: bool = False


class SendKeys(BaseModel):
    keys: list[str]  # tmux key names: "Enter", "C-c", "Escape", etc.


class ChatMessage(BaseModel):
    text: str
    user: str = "anon"
