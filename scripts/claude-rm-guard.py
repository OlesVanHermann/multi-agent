#!/usr/bin/env python3
"""Hook PreToolUse (Bash) : refuse toute invocation de rm / rmdir / unlink.

CLAUDE.md interdit la suppression définitive (`rm -rf`, `rm -r`, `rm`, `rmdir`,
`unlink`) : il faut `mv` vers `$BASE/removed/` ou `safe_rm`. Ce garde rend
l'interdiction **vérifiable** au lieu de déclarative.

Il refuse une commande qui INVOQUE l'un de ces binaires **en position de
commande**, y compris :
  - après `;`, `&&`, `||`, `|` ;
  - dans une substitution `$( … )` ou `` `…` `` et dans un sous-shell `( … )` ;
  - via `sh -c` / `bash -c '<cmd>'` ;
  - via `xargs rm` ;
  - via `find … -delete` et `find … -exec rm` ;
  - derrière un wrapper (`sudo`, `env`, `command`, `nice`, `nohup`, …).

Il ne bloque JAMAIS une simple MENTION citée : `echo 'rm -rf'`, `grep 'rm -rf'`
ou un message `send.sh` contenant « rm -rf /dev/null » passent, parce que le
motif n'y est pas en position de commande.

I/O du hook : lit le JSON PreToolUse sur stdin (`tool_name`, `tool_input`).
Sortie : exit 2 + message sur stderr = refus ; exit 0 = autorisé.
"""

import json
import sys

TARGETS = {"rm", "rmdir", "unlink"}
SHELLS = {"sh", "bash", "dash", "ash", "zsh", "ksh"}
# Wrappers : le vrai binaire est leur premier argument non-option / non-VAR=val.
WRAPPERS = {"sudo", "doas", "env", "command", "nice", "ionice", "nohup",
            "setsid", "stdbuf", "builtin", "exec"}
# Options de wrapper qui consomment la valeur suivante.
WRAPPER_VALUE_FLAGS = {"-u", "-g", "-n", "-c", "-p", "-r", "-t", "-C",
                       "-i", "-o", "-e", "-P"}
XARGS_VALUE_FLAGS = {"-I", "-E", "-n", "-P", "-s", "-L", "-d", "-a",
                     "--max-args", "--max-procs", "--delimiter",
                     "--replace", "--arg-file", "--max-lines"}
SEPARATORS = {";", "&&", "||", "|", "|&", "&", "\n", "(", ")"}
CMD_START = {";", "&&", "||", "|", "|&", "&", "\n", "("}
MAX_DEPTH = 25

DENY_MESSAGE = (
    "Suppression interdite (CLAUDE.md) : `{name}` détecté en position de "
    "commande. Ne jamais `rm`/`rmdir`/`unlink` : déplace vers la corbeille — "
    "`mv <cible> $BASE/removed/$(date +%Y%m%d_%H%M%S)_<nom>` — ou `safe_rm "
    "<cible>`."
)


def base_name(word):
    """Nom de binaire, chemin retiré : `/bin/rm` -> `rm`, `./rm` -> `rm`."""
    return word.rsplit("/", 1)[-1]


def _read_balanced(s, i):
    """`i` pointe juste après un `$(`. Retourne (contenu, index_apres_`)`)."""
    depth = 1
    start = i
    n = len(s)
    while i < n and depth:
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return s[start:i], i + 1
        elif c == "'":
            j = s.find("'", i + 1)
            i = j if j != -1 else n
        elif c == '"':
            i = _skip_dquote(s, i + 1)
            continue
        i += 1
    return s[start:i], i


def _skip_dquote(s, i):
    """`i` pointe juste après le `"` ouvrant. Retourne l'index après le `"`."""
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == '"':
            return i + 1
        i += 1
    return i


def tokenize(s):
    """Découpe une commande en tokens, en respectant les guillemets.

    Retourne (tokens, subcommands) :
      - tokens : liste de ("op", texte) pour les séparateurs, ("word", unquoted)
        pour les mots. Le contenu cité fait partie du mot (jamais un opérateur).
      - subcommands : chaînes internes des substitutions `$( )` / `` ` `` et des
        sous-shells (`( )` capté comme opérateur, son contenu reste dans le flux)
        — chacune est réanalysée comme une commande à part entière.
    """
    tokens = []
    subcmds = []
    word = []
    has_word = False
    i, n = 0, len(s)

    def endword():
        nonlocal word, has_word
        if has_word:
            tokens.append(("word", "".join(word)))
        word = []
        has_word = False

    while i < n:
        c = s[i]
        # Guillemets simples : littéral, aucune substitution.
        if c == "'":
            j = s.find("'", i + 1)
            if j == -1:
                j = n
            word.append(s[i + 1:j])
            has_word = True
            i = j + 1
            continue
        # Guillemets doubles : $( ) et ` ` restent actifs.
        if c == '"':
            i += 1
            while i < n and s[i] != '"':
                if s[i] == "\\" and i + 1 < n and s[i + 1] in '"\\$`':
                    word.append(s[i + 1])
                    has_word = True
                    i += 2
                    continue
                if s[i] == "$" and i + 1 < n and s[i + 1] == "(":
                    inner, i = _read_balanced(s, i + 2)
                    subcmds.append(inner)
                    word.append("X")
                    has_word = True
                    continue
                if s[i] == "`":
                    j = s.find("`", i + 1)
                    if j == -1:
                        j = n
                    subcmds.append(s[i + 1:j])
                    word.append("X")
                    has_word = True
                    i = j + 1
                    continue
                word.append(s[i])
                has_word = True
                i += 1
            i += 1
            continue
        # Échappement hors guillemets.
        if c == "\\" and i + 1 < n:
            word.append(s[i + 1])
            has_word = True
            i += 2
            continue
        # Substitution de commande $( … ) hors guillemets.
        if c == "$" and i + 1 < n and s[i + 1] == "(":
            inner, i = _read_balanced(s, i + 2)
            subcmds.append(inner)
            word.append("X")
            has_word = True
            continue
        # ${VAR} : expansion de paramètre, reste dans le mot.
        if c == "$" and i + 1 < n and s[i + 1] == "{":
            word.append("$")
            has_word = True
            i += 1
            continue
        # Backtick hors guillemets.
        if c == "`":
            j = s.find("`", i + 1)
            if j == -1:
                j = n
            subcmds.append(s[i + 1:j])
            word.append("X")
            has_word = True
            i = j + 1
            continue
        # Opérateurs à deux caractères.
        two = s[i:i + 2]
        if two in ("&&", "||", "|&"):
            endword()
            tokens.append(("op", two))
            i += 2
            continue
        if c in ";|&()\n":
            endword()
            tokens.append(("op", c))
            i += 1
            continue
        # Groupe { … } : opérateur seulement s'il est isolé (début de mot et
        # suivi d'un blanc/fin) — `${VAR}` est déjà géré plus haut.
        if c in "{}" and not has_word and (i + 1 >= n or s[i + 1] in " \t\n"):
            endword()
            tokens.append(("op", c))
            i += 1
            continue
        if c in " \t":
            endword()
            i += 1
            continue
        word.append(c)
        has_word = True
        i += 1
    endword()
    return tokens, subcmds


def _xargs_command(args):
    """Commande lancée par xargs : premier mot non-option, en sautant la valeur
    des options qui en consomment une."""
    k = 0
    while k < len(args):
        a = args[k]
        if a in XARGS_VALUE_FLAGS:
            k += 2
            continue
        if a.startswith("-"):
            k += 1
            continue
        return args[k:]
    return []


def _wrapper_inner(args):
    """Commande réelle derrière un wrapper (sudo/env/…) : on saute options,
    valeurs d'options et affectations VAR=val."""
    k = 0
    while k < len(args):
        a = args[k]
        if a in WRAPPER_VALUE_FLAGS:
            k += 2
            continue
        if a.startswith("-"):
            k += 1
            continue
        # Affectation d'environnement (env A=b cmd, ou VAR=val cmd).
        eq = a.find("=")
        if eq > 0 and a[:eq].replace("_", "a").isalnum() and "/" not in a[:eq]:
            k += 1
            continue
        return args[k:]
    return []


def _check_find(args, depth):
    """`find … -delete` / `find … -exec rm …` interdits."""
    for k, a in enumerate(args):
        if a == "-delete":
            return "find … -delete"
        if a in ("-exec", "-execdir") and k + 1 < len(args):
            if base_name(args[k + 1]) in TARGETS:
                return f"find … {a} {base_name(args[k + 1])}"
    return ""


def check_simple_command(words, depth=0):
    """Analyse UNE commande simple (nom + arguments, déjà déquotés)."""
    if not words or depth > MAX_DEPTH:
        return ""
    name = words[0]
    base = base_name(name)
    rest = words[1:]
    if base in TARGETS:
        return DENY_MESSAGE.format(name=base)
    if base in SHELLS:
        for k, w in enumerate(rest):
            if w == "-c" and k + 1 < len(rest):
                return scan(rest[k + 1], depth + 1)
        return ""
    if base == "xargs":
        return check_simple_command(_xargs_command(rest), depth + 1)
    if base in ("find", "gfind"):
        return _check_find(rest, depth)
    if base in WRAPPERS:
        return check_simple_command(_wrapper_inner(rest), depth + 1)
    return ""


def scan(command, depth=0):
    """Retourne un message de refus si la commande invoque rm/rmdir/unlink,
    sinon une chaîne vide."""
    if not command or depth > MAX_DEPTH:
        return ""
    tokens, subcmds = tokenize(command)
    # Les substitutions et sous-shells embarqués sont des listes de commandes.
    for inner in subcmds:
        reason = scan(inner, depth + 1)
        if reason:
            return reason
    # Le flux restant se découpe en commandes simples sur les séparateurs.
    words = []
    for kind, text in tokens:
        if kind == "op":
            reason = check_simple_command(words, depth)
            if reason:
                return reason
            words = []
            continue
        words.append(text)
    return check_simple_command(words, depth)


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    command = (data.get("tool_input") or {}).get("command", "")
    if not isinstance(command, str) or not command.strip():
        return 0
    reason = scan(command)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
