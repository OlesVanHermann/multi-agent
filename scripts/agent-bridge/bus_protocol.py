#!/usr/bin/env python3
"""Publisher Redis atomique du protocole inter-agent ``ma.bus.v1``.

Les scripts shell gardent leur interface historique. Ce module centralise les
identifiants stables, la resolution du contexte de tour et l'appel de la
transaction Lua. Aucun contenu metier n'est interprete par le publisher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

import redis


SCHEMA = "ma.bus.v1"
ROOT = Path(__file__).resolve().parents[2]
LUA_PATH = Path(__file__).with_name("publish_event.lua")
REPORT_STATUSES = {"SUCCESS", "PARTIAL", "FAILED", "BLOCKED", "INFO_REQUIRED"}
TERMINAL_EVENTS = {
    "DONE", "SCORE", "BLOCKED", "INFO_REQUIRED", "ERROR",
    "ARTIFACT_READY", "PROTOCOL_ERROR", "ARBITRAGE", "CONCLUSION",
    "PROMPT_RELOADED",
}
MESSAGE_RESCUES = {"INFO_REQUIRED", "PROTOCOL_ERROR", "STATUS_REQUIRED"}
TERMINAL_RESCUES = {"INFO_REQUIRED", "PROTOCOL_ERROR"}
BLOCKING_EVENTS = {"BLOCKED", "INFO_REQUIRED"}
# A8 : fraîcheur maximale du contexte last_* (enveloppe conservée par le
# bridge après la fin du tour). Au-delà, retour au comportement rescue.
LAST_TURN_CONTEXT_TTL = int(os.environ.get("MA_LAST_TURN_CONTEXT_TTL", 7200))


class ProtocolError(RuntimeError):
    """Erreur de contrat avec un code de sortie stable."""

    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


def _load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / "setup" / "secrets.cfg"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "REDIS_DB"}:
            values[key] = value.strip().strip("'\"")
    return values


def redis_client() -> redis.Redis:
    config = _load_config()

    def endpoint_value(name: str, default: str) -> str:
        # Une valeur d'environnement explicitement vide neutralise elle aussi
        # secrets.cfg, comme redis.sh. Les deux publishers doivent viser la
        # meme instance dans tous les cas.
        if name in os.environ:
            return os.environ[name] or default
        return config.get(name) or default

    host = endpoint_value("REDIS_HOST", "localhost")
    port_text = endpoint_value("REDIS_PORT", "6379")
    db_text = endpoint_value("REDIS_DB", "0")
    password = os.environ.get("REDIS_PASSWORD")
    if password is None:
        password = config.get("REDIS_PASSWORD", "")
    try:
        port = int(port_text)
        db = int(db_text)
    except ValueError as exc:
        raise ProtocolError("invalid: REDIS_PORT and REDIS_DB must be integers") from exc
    if not 1 <= port <= 65535 or db < 0:
        raise ProtocolError(
            "invalid: REDIS_PORT must be 1..65535 and REDIS_DB must be non-negative")
    return redis.Redis(
        host=host,
        port=port,
        db=db,
        password=password or None,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=10,
    )


def _missing(value: object) -> bool:
    return str(value or "").strip().lower() in {"", "none", "unknown"}


def _stable_id(prefix: str, *parts: object) -> str:
    material = json.dumps(
        [SCHEMA, prefix, *(str(part or "") for part in parts)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(material).hexdigest()}"


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _state(client: redis.Redis, from_agent: str) -> dict[str, str]:
    if from_agent in {"cli", "manual"}:
        return {}
    try:
        return client.hgetall(f"agent:{from_agent}")
    except redis.RedisError as exc:
        raise ProtocolError(f"publish-error: Redis context read failed: {exc}", 1) from exc


def resolve_context(client: redis.Redis, args: argparse.Namespace) -> dict[str, str]:
    state = _state(client, args.from_agent)
    inter_agent = args.from_agent not in {"cli", "manual"}

    # A8 : le bridge conclut souvent un tour pendant que le modèle travaille
    # encore (bashes en arrière-plan). Les current_* sont alors effacés et
    # chaque rapport partait en TASK=unattributed / CORR=rescue-*. Le contexte
    # last_* écrit par le bridge à la fin du tour reste utilisable tant qu'il
    # est frais. Le tour (source_turn_id) n'hérite JAMAIS de ce repli : la
    # déduplication des rapports est par tour, deux rapports post-tour doivent
    # rester deux tours distincts.
    try:
        last_ended = int(state.get("last_turn_ended_at", "") or 0)
    except (TypeError, ValueError):
        last_ended = 0
    last_fresh = bool(last_ended) and (
        time.time() - last_ended) <= LAST_TURN_CONTEXT_TTL

    def choose(explicit: str, state_name: str, *, causal: bool = False,
               fallback: str = "") -> str:
        candidate = state.get(state_name, "")
        explicit_value = "" if _missing(explicit) else str(explicit)
        state_value = "" if _missing(candidate) else str(candidate)
        if (causal and inter_agent and explicit_value and state_value
                and explicit_value != state_value):
            raise ProtocolError(
                f"METADATA_CONFLICT field={state_name} "
                f"explicit={explicit_value} snapshot={state_value}", 3)
        value = explicit_value or state_value
        if not value and fallback and last_fresh:
            fallback_value = state.get(fallback, "")
            if not _missing(fallback_value):
                value = str(fallback_value)
        return value

    task_id = choose(args.task_id, "current_task_id", causal=True,
                     fallback="last_task_id")
    cycle = choose(args.cycle, "current_cycle", causal=True,
                   fallback="last_cycle")
    correlation_id = choose(args.correlation_id, "current_correlation",
                            causal=True, fallback="last_correlation")
    source_turn_id = choose(args.source_turn_id, "current_turn_id", causal=True)
    requester = choose(args.requester, "current_requester",
                       fallback="last_requester")
    owner = choose(args.owner, "current_owner", fallback="last_owner")
    origin = choose(args.origin, "current_turn_origin",
                    fallback="last_turn_origin")

    if not source_turn_id:
        source_turn_id = f"turn-{uuid.uuid4()}"

    event = str(args.event or "").upper()
    if args.kind == "report":
        task_id = task_id or "unattributed"
        cycle = cycle or "unattributed"
        correlation_id = correlation_id or _stable_id(
            "rescue", args.from_agent, source_turn_id)
        requester = requester or args.to_agent
        owner = owner or args.to_agent
        origin = origin or "direct"
    elif inter_agent and (not task_id or not cycle or not correlation_id):
        rescue_allowed = (
            event in MESSAGE_RESCUES if args.kind == "message"
            else event in TERMINAL_RESCUES
        )
        if not rescue_allowed:
            noun = "message" if args.kind == "message" else "terminal"
            raise ProtocolError(
                f"invalid: inter-agent {noun} requires TASK_ID, CYCLE and CORRELATION_ID")
        task_id = task_id or "unattributed"
        cycle = cycle or "unattributed"
        correlation_id = correlation_id or _stable_id(
            "rescue", args.from_agent, source_turn_id)
        print(
            f"rescue: incomplete metadata, emitting {event} under "
            f"corr={correlation_id}",
            file=sys.stderr,
        )
    else:
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

    if args.kind == "message" and event == "DISPATCH" and not args.expected_event:
        raise ProtocolError("invalid: DISPATCH requires EXPECTED_EVENT")

    if args.kind == "message":
        requester = requester or args.from_agent
        owner = owner or args.from_agent
    elif args.kind == "terminal":
        requester = requester or args.to_agent
        owner = owner or args.to_agent
    origin = origin or ("operator" if not inter_agent else "agent")

    return {
        "source_turn_id": source_turn_id,
        "task_id": task_id,
        "cycle": cycle,
        "correlation_id": correlation_id,
        "requester": requester,
        "owner": owner,
        "origin": origin,
    }


def _common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from-agent", required=True)
    parser.add_argument("--to-agent", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--source-turn-id", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--cycle", default="")
    parser.add_argument("--correlation-id", default="")
    parser.add_argument("--requester", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--origin", default="")
    parser.add_argument("--expected-event", default="")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    if parsed > (1 << 63) - 1:
        raise argparse.ArgumentTypeError("exceeds Redis signed integer range")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    context = sub.add_parser("context")
    _common_parser(context)
    context.add_argument("--kind", choices=("message", "terminal", "report"), required=True)

    message = sub.add_parser("message")
    _common_parser(message)
    message.add_argument("--prompt", required=True)
    message.add_argument("--maxlen", type=_positive_int, default=10000)
    message.add_argument("--ttl", type=_positive_int, default=604800)

    terminal = sub.add_parser("terminal")
    _common_parser(terminal)
    terminal.add_argument("--signal", required=True)
    terminal.add_argument("--completion-maxlen", type=_positive_int, default=1000)
    terminal.add_argument("--inbox-maxlen", type=_positive_int, default=10000)
    terminal.add_argument("--ttl", type=_positive_int, default=604800)

    report = sub.add_parser("report")
    _common_parser(report)
    report.add_argument("--summary", required=True)
    report.add_argument("--artifact", default="NONE")
    report.add_argument("--tests", default="NOT_RUN")
    report.add_argument("--next", default="NONE")
    report.add_argument("--duration", default="NON MESURE")
    report.add_argument("--report-maxlen", type=_positive_int, default=10000)
    report.add_argument("--inbox-maxlen", type=_positive_int, default=10000)
    report.add_argument("--ttl", type=_positive_int, default=604800)
    return parser


def _eval(client: redis.Redis, keys: list[str], argv: list[object]) -> list[str]:
    try:
        source = LUA_PATH.read_text(encoding="utf-8")
        result = client.eval(source, len(keys), *keys, *(str(value) for value in argv))
    except (OSError, redis.RedisError) as exc:
        raise ProtocolError(f"publish-error: atomic Redis publication failed: {exc}", 1) from exc
    return [str(value or "") for value in result]


def _context_args(args: argparse.Namespace, kind: str) -> dict[str, str]:
    args.kind = kind
    return resolve_context(redis_client(), args)


def publish_message(client: redis.Redis, args: argparse.Namespace, ctx: dict[str, str]) -> list[str]:
    event = args.event.upper()
    event_id = _stable_id(
        "event", "message", args.from_agent, args.to_agent,
        ctx["source_turn_id"], event, ctx["task_id"], ctx["cycle"],
        ctx["correlation_id"], _fingerprint({"prompt": args.prompt}),
    )
    fingerprint = _fingerprint({
        "event": event,
        "prompt": args.prompt,
        "from": args.from_agent,
        "to": args.to_agent,
        **ctx,
        "expected_event": args.expected_event,
    })
    keys = [
        f"agent:{args.to_agent}:inbox",
        f"ma:bus:v1:event:{event_id}",
    ]
    argv = [
        "message", SCHEMA, str(int(time.time())), args.maxlen,
        args.ttl, args.from_agent, args.to_agent, event, args.prompt,
        ctx["correlation_id"], ctx["task_id"], ctx["cycle"],
        ctx["requester"], ctx["owner"], args.expected_event,
        ctx["source_turn_id"], event_id, fingerprint,
        _stable_id(
            "decision", args.from_agent, ctx["source_turn_id"],
            ctx["task_id"], ctx["cycle"], ctx["correlation_id"]),
        "1" if event in BLOCKING_EVENTS else "0",
        ctx["origin"],
    ]
    # Les trois derniers arguments sont decision_id, is_blocking, origin.
    # La clé Redis doit porter la même identité que le champ ARGV[19] ;
    # pointer sur -2 utiliserait littéralement ``1`` pour tout blocage et
    # neutraliserait la déduplication report/send par destinataire.
    decision_id = argv[-3]
    keys.append(f"ma:bus:v1:decision:{decision_id}")
    return _eval(client, keys, argv)


def publish_terminal(client: redis.Redis, args: argparse.Namespace, ctx: dict[str, str]) -> list[str]:
    event = args.event.upper()
    if event not in TERMINAL_EVENTS:
        raise ProtocolError(f"invalid: unsupported terminal event {event}")
    event_id = _stable_id(
        "event", "terminal", args.from_agent, args.to_agent,
        ctx["source_turn_id"], event, ctx["task_id"], ctx["cycle"],
        ctx["correlation_id"],
    )
    decision_id = _stable_id(
        "decision", args.from_agent, ctx["source_turn_id"],
        ctx["task_id"], ctx["cycle"], ctx["correlation_id"],
    )
    fingerprint = _fingerprint({
        "event": event,
        "signal": args.signal,
        "from": args.from_agent,
        "to": args.to_agent,
        **ctx,
    })
    # A9 : slot LOGIQUE du terminal, indépendant du tour. Constat 22/08
    # (triangle 334) : un done.sh émis hors-tour puis rejoué dans le tour
    # suivant portait deux source_turn_id, donc deux event_id — le rejeu
    # strict passait pour un nouveau terminal et le Master consommait deux
    # tours pour la même livraison. L'identité du slot est
    # (émetteur, cible, événement, tâche, cycle, corrélation) et son
    # empreinte de contenu exclut le tour et l'origine : contenu identique
    # → ALREADY_DELIVERED ; contenu différent → NOT_DELIVERED (nouveau
    # CYCLE/CORR requis), quel que soit le tour.
    slot_id = _stable_id(
        "slot", "terminal", args.from_agent, args.to_agent, event,
        ctx["task_id"], ctx["cycle"], ctx["correlation_id"],
    )
    slot_fingerprint = _fingerprint({
        "event": event,
        "signal": args.signal,
        "from": args.from_agent,
        "to": args.to_agent,
        "task_id": ctx["task_id"],
        "cycle": ctx["cycle"],
        "correlation_id": ctx["correlation_id"],
    })
    prompt = (
        f"EVENT:{event}|TASK:{ctx['task_id']}|CYCLE:{ctx['cycle']}|"
        f"CORR:{ctx['correlation_id']}|DETAIL:{args.signal}"
    )
    keys = [
        "completion",
        f"agent:{args.to_agent}:inbox",
        f"ma:bus:v1:terminal:{event_id}",
        f"ma:bus:v1:decision:{decision_id}",
        f"ma:bus:v1:terminal-slot:{slot_id}",
    ]
    argv = [
        "terminal", SCHEMA, str(int(time.time())),
        args.completion_maxlen, args.inbox_maxlen, args.ttl,
        args.from_agent, args.to_agent, event, args.signal, prompt,
        ctx["correlation_id"], ctx["task_id"], ctx["cycle"],
        ctx["requester"], ctx["owner"], ctx["source_turn_id"],
        event_id, decision_id, fingerprint,
        "1" if event in BLOCKING_EVENTS else "0",
        ctx["origin"],
        slot_fingerprint,
    ]
    return _eval(client, keys, argv)


def publish_report(client: redis.Redis, args: argparse.Namespace, ctx: dict[str, str]) -> list[str]:
    status = args.event.upper()
    if status not in REPORT_STATUSES:
        raise ProtocolError(f"invalid: unsupported report status {status}")
    report_id = _stable_id("report", args.from_agent, ctx["source_turn_id"])
    report_event_id = _stable_id("event", "report", report_id)
    decision_id = _stable_id(
        "decision", args.from_agent, ctx["source_turn_id"],
        ctx["task_id"], ctx["cycle"], ctx["correlation_id"],
    )
    wake_event_id = _stable_id("event", "decision", decision_id, args.to_agent)
    detail = (
        f"STATUS={status}|SUMMARY={args.summary}|ARTIFACT={args.artifact}|"
        f"TESTS={args.tests}|NEXT={args.next}|DURATION={args.duration}|"
        f"TURN_ID={ctx['source_turn_id']}|ORIGIN={ctx['origin']}|"
        f"SOURCE_CORR={ctx['correlation_id']}"
    )
    fingerprint = _fingerprint({
        "status": status,
        "summary": args.summary,
        "artifact": args.artifact,
        "tests": args.tests,
        "next": args.next,
        "duration": args.duration,
        "origin": ctx["origin"],
        "from": args.from_agent,
        "to": args.to_agent,
        **ctx,
    })
    # Le rapport est TOUJOURS livré au coordinateur ; seul son en-tête dit
    # s'il appelle une décision. Annoncer « BLOCAGE SUCCESS » serait mentir
    # sur la nature du message pour la seule raison qu'il emprunte le même
    # canal.
    wake_prompt = (
        f"[BLOCAGE {status} de {args.from_agent}] {args.summary}"
        if status in BLOCKING_EVENTS
        else f"[RAPPORT {status} de {args.from_agent}] {args.summary}"
    )
    keys = [
        f"agent:{args.to_agent}:reports",
        f"agent:{args.to_agent}:inbox",
        f"agent:{args.from_agent}",
        f"ma:bus:v1:report:{report_id}",
        f"ma:bus:v1:decision:{decision_id}",
    ]
    argv = [
        "report", SCHEMA, str(int(time.time())),
        args.report_maxlen, args.inbox_maxlen, args.ttl,
        args.from_agent, args.to_agent, status, args.summary,
        args.artifact, args.tests, args.next, args.duration, ctx["origin"],
        ctx["correlation_id"], ctx["task_id"], ctx["cycle"],
        ctx["requester"], ctx["owner"], ctx["source_turn_id"],
        report_id, report_event_id, decision_id, wake_event_id,
        fingerprint, detail, wake_prompt,
        "1" if status in BLOCKING_EVENTS else "0",
    ]
    return _eval(client, keys, argv)


def main() -> int:
    args = build_parser().parse_args()
    try:
        client = redis_client()
        kind = args.kind if args.command == "context" else args.command
        ctx = resolve_context(client, args if args.command == "context" else _with_kind(args, kind))
        if args.command == "context":
            print("|".join([
                "CONTEXT", ctx["source_turn_id"], ctx["task_id"],
                ctx["cycle"], ctx["correlation_id"], ctx["requester"],
                ctx["owner"], ctx["origin"],
            ]))
            return 0
        if args.command == "message":
            result = publish_message(client, args, ctx)
        elif args.command == "terminal":
            result = publish_terminal(client, args, ctx)
        else:
            result = publish_report(client, args, ctx)
        print("|".join(result))
        if result and result[0] == "CONFLICT":
            return 3
        return 0
    except ProtocolError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code


def _with_kind(args: argparse.Namespace, kind: str) -> argparse.Namespace:
    args.kind = kind
    return args


if __name__ == "__main__":
    raise SystemExit(main())
