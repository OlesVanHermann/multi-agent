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
    type: str          # "login" or "model"
    value: str         # "claude2a" or "" to remove override


class EffortUpdate(BaseModel):
    agent_id: str      # "300" or "default"
    level: str         # "L", "M", "H", or "" (remove override)


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
