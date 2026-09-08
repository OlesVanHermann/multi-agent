#!/usr/bin/env python3
"""Ajoute un contrat résultat-first aux prompts existants (migration idempotente)."""

import argparse
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
MARKER = "## Priorité au résultat"
CREATOR_MARKER = "## Contrat de création résultat-first"
DELIVERY_MARKER = "## Contrat de livraison piloté par les preuves"
LEGACY_CONTRADICTOR_SCOPE_MARKER = "## Scope triangle et relance du développement"
CONTRADICTOR_SCOPE_MARKER = "## Audit de l'exécution de la demande utilisateur — v3.2.7"
CONTRADICTOR_METHOD_MARKER = "## Méthode d'audit utilisateur — v3.2.7"
CONTRADICTOR_FALLBACK_MARKER = "### Demande utilisateur non attribuée"
LEGACY_COMMUNICATION_MARKER = "## Contrat de communication déterministe"
PREVIOUS_COMMUNICATION_MARKER = "## Contrat de communication utile — v3.2.12"
COMMUNICATION_MARKER = "## Contrat de communication utile — v3.2.19"
USER_AUTHORITY_MARKER = "## Autorité décisionnelle de l'utilisateur — v3.2.20"
DEV_TEST_ORCHESTRATION_MARKER = "## Orchestration développement et tests — v3.2.22"
LEGACY_DEV_TEST_ORCHESTRATION_MARKER = "## Orchestration développement et tests — v3.2.20"
PERIODIC_OPTIMIZER_MARKER = "## Cascade des tâches planifiées — v3.2.22"


def is_creator(path):
    return path.parent.name.startswith(("150-create-", "160-create-", "170-create-"))


def purpose(path, text):
    title = next((line.lower() for line in text.splitlines() if line.startswith("# ")), "")
    sample = f"{path.parent.name.lower()} {path.name.lower()} {title}"
    if "hub manager" in sample:
        return "intégrer, vérifier et publier les évolutions du framework de manière fiable"
    if "create-" in sample or "créateur" in sample or "creation" in sample:
        return "créer des agents orientés vers leur résultat métier plutôt que vers la narration du processus"
    if "contradictor" in sample:
        return ("donner au 1XX une vue factuelle de tout le triangle et une "
                "relance de développement directement actionnable")
    if "curator" in sample:
        return "donner au producteur le contexte minimal, actuel et vérifiable qui lui permet de réussir"
    if "coach" in sample:
        return "augmenter la probabilité de réussite du prochain cycle sans changement méthodologique inutile"
    if "observer" in sample or "tester" in sample or "reviewer" in sample:
        return "établir si le résultat répond réellement au besoin, avec des preuves et des défauts actionnables"
    if "developer" in sample or "dévelop" in sample or re.search(r"\bdev\b", sample):
        return "produire un livrable métier fonctionnel, intégré et vérifié"
    if "architect" in sample:
        return "maintenir une structure qui permet aux autres agents de produire sans friction inutile"
    if "master" in sample:
        return "faire aboutir la demande jusqu'à un résultat métier livré et vérifié"
    if "explorer" in sample:
        return "transformer le besoin et l'état réel en spécification exploitable et vérifiable"
    if "integrator" in sample or "merge" in sample:
        return "intégrer les contributions en un ensemble cohérent et fonctionnel"
    if "releaser" in sample or "release" in sample:
        return "livrer une version vérifiée, traçable et réellement publiable"
    return "accomplir la mission fonctionnelle décrite ci-dessous et livrer un résultat vérifiable"


def delivery_contract(path, text):
    """Contrat spécialisé qui empêche le score mou de remplacer la livraison."""
    title = next((line.lower() for line in text.splitlines() if line.startswith("# ")), "")
    sample = f"{path.parent.name.lower()} {path.name.lower()} {title}"
    if "contradictor" in sample or is_creator(path):
        return ""
    if "principal mono" in sample or "mono principal" in sample:
        body = """
Tu portes directement la mission jusqu'au résultat intégré, aux vérifications
dans la destination réelle et à DONE. Le Contradictor t'aide à corriger ta
décision mais n'est ni un Observer ni un gate de livraison. Aucun score ou
processus satellite ne remplace tes critères d'acceptation observables.
"""
    elif "master" in sample or re.search(r"-1\d\d-system\.md$", path.name):
        body = """
- Tu es propriétaire de la livraison jusqu'à l'intégration réelle, aux tests
  post-intégration et au passage de la tâche à DONE.
- `BLOCK_DEV` renvoie uniquement les défauts bloquants au Developer.
- `READY_FOR_INTEGRATION` déclenche immédiatement la Phase C.
- `BLOCK_INTEGRATION` se traite dans la Phase C sans refaire le développement.
- `ACCEPT_WITH_IMPROVEMENTS` signifie intégrer et clôturer, puis transmettre
  les améliorations facultatives au Coach.
- Les hard gates et critères d'acceptation obligatoires décident de la
  livrabilité. Un score qualitatif, même inférieur à 98, ne déclenche jamais à
  lui seul un nouveau cycle.
"""
    elif "observer" in sample or "tester" in sample or "reviewer" in sample or re.search(r"-5\d\d-system\.md$", path.name):
        body = """
Sépare obligatoirement : `DEV_BLOCKERS`, `INTEGRATION_ACTIONS` et
`OPTIONAL_IMPROVEMENTS`. Termine le bilan par exactement un verdict :
`BLOCK_DEV`, `READY_FOR_INTEGRATION`, `BLOCK_INTEGRATION` ou
`ACCEPT_WITH_IMPROVEMENTS`. Les hard gates et critères obligatoires déterminent
le verdict ; le score qualitatif informe les améliorations et ne bloque pas une
livraison autrement valide.
"""
    elif "developer" in sample or re.search(r"-3\d\d-system\.md$", path.name):
        body = """
Livre un paquet directement intégrable avec `RESULT`, `CHANGED_FILES`,
`TESTS_RUN`, `ACCEPTANCE_EVIDENCE`, `INTEGRATION_COMMANDS` et
`KNOWN_LIMITATIONS`. `CHANGES.md` donne les destinations et commandes exactes.
La qualité du paquet réduit la Phase C ; la décision d'acceptation appartient à
l'Observer et l'intégration au Master.
"""
    elif "curator" in sample or re.search(r"-7\d\d-system\.md$", path.name):
        body = """
Interviens avant le développement pour fournir le contexte manquant. Ne sois
pas rappelé automatiquement après un score imparfait : un nouveau passage exige
une preuve d'information absente, périmée ou mal routée.
"""
    elif "coach" in sample or re.search(r"-8\d\d-system\.md$", path.name):
        body = """
Ton travail améliore le prochain cycle et ne bloque jamais l'intégration d'un
résultat livrable. Produis une candidate en parallèle ou après la Phase C. Son
absence, sa non-promotion ou un score qualitatif inférieur à 98 ne rouvrent pas
la tâche acceptée.
"""
    elif "architect" in sample or re.search(r"-9\d\d-system\.md$", path.name):
        body = """
Interviens pour une incohérence structurelle, un problème transversal répété ou
un arbitrage impossible localement. Une correction projet ordinaire, une Phase
C ou un score qualitatif imparfait ne nécessitent pas ton autorisation.
"""
    else:
        return ""
    return f"\n\n{DELIVERY_MARKER}\n\n{body.strip()}\n"


def contradictor_scope_contract(path, text):
    """Étend les Contradictors existants sans réécrire leur prompt métier."""
    title = next((line.lower() for line in text.splitlines() if line.startswith("# ")), "")
    sample = f"{path.parent.name.lower()} {path.name.lower()} {title}"
    if "contradictor" not in sample and not re.search(r"-2\d\d-system\.md$", path.name):
        return ""
    return f"""

{CONTRADICTOR_SCOPE_MARKER}

- Commence par identifier la demande adressée par l'utilisateur au `NNN-1XX`,
  ses corrections ultérieures et le dernier résultat attendu.
- Distingue strictement `USER_REQUEST`, `AGENT_INSTRUCTION`,
  `INTER_AGENT_MESSAGE` et `PHYSICAL_EVIDENCE`. Les fichiers `system.md`,
  `memory.md` et `methodology.md` ne sont jamais des prompts utilisateur.
- Reconstitue ensuite les échanges de tous les agents `NNN-YXX`, puis confronte
  leurs déclarations au code, aux artefacts, commits, hashes et tests.
- Qualifie séparément l'exécution du prompt, le développement, la validation et
  la livraison avec `OUI`, `PARTIEL`, `NON` ou `INDÉTERMINÉ`.
- Pour tout écart, donne au `NNN-1XX` le plan de développement ou correction,
  les agents à mobiliser, l'ordre de relance et les critères d'acceptation.
- Le seul destinataire autorisé de `envoie` reste le `NNN-1XX`. N'envoie jamais
  la conclusion directement aux satellites.
- Un `DONE`, un échange ou un fichier modifié ne prouve jamais seul le résultat.
"""


def contradictor_methodology_contract():
    return f"""

{CONTRADICTOR_METHOD_MARKER}

Cet ordre remplace toute séquence antérieure contradictoire :

1. `USER_REQUEST` : demande initiale au `1XX`, amendements, résultat attendu.
   Si elle est absente, les historiques/panes sont seulement des candidats non
   attribués ; ne jamais substituer un prompt d'agent.
2. `AGENT_INSTRUCTION` : rôles et contraintes, sans les confondre avec la demande.
3. `INTER_AGENT_MESSAGE` : décisions, dispatchs, réponses et terminaux de tout le triangle.
4. `PHYSICAL_EVIDENCE` : code, artefacts, commits, hashes et tests.
5. Verdict séparé sur exécution, développement, validation et livraison.
6. Écart causal puis plan concret jusqu'au résultat final attendu.

La conclusion contient toutes les rubriques canoniques de
`docs/CONTRADICTOR.md`. Une preuve absente vaut `INDÉTERMINÉ`.

{CONTRADICTOR_FALLBACK_MARKER}

Si `analysis_view.user_requests` est vide, les historiques et panes du `1XX`
restent des candidats non attribués. Leur origine incertaine impose
`INDÉTERMINÉ`; un prompt d'agent ne les remplace jamais.
"""


def contradictor_fallback_contract():
    return f"""

{CONTRADICTOR_FALLBACK_MARKER}

Si `analysis_view.user_requests` est vide, les historiques et panes du `1XX`
ne sont que des candidats non attribués. Signale cette incertitude et conclus
`INDÉTERMINÉ` si leur origine ne peut être établie. Ne substitue jamais un
fichier `system.md`, `memory.md` ou `methodology.md` à la demande utilisateur.
"""


def communication_contract(path, text):
    """Contrat commun : enveloppe autoritaire, terminal unique et preuves."""
    title = next((line.lower() for line in text.splitlines() if line.startswith("# ")), "")
    sample = f"{path.parent.name.lower()} {path.name.lower()} {title}"
    body = """
- Tout agent généré classe ses émissions
  `ACTION|STATUS|TERMINAL|NOOP`. `NOOP` impose le silence : aucun ACK de
  courtoisie, suivi inchangé ou ponctuation isolée.
- Tout Master généré maintient un `USER_RESULT_CONTRACT`, agrège ses
  sous-cycles et choisit après chaque terminal exactement
  `CLOSED_SUCCESS|NEXT_CYCLE_OPENED|USER_BLOCKED|CLOSED_FAILED`.
- Toute tâche différée conserve `QUEUED_TASK`, `BLOCKED_BY` et
  `RESUME_EVENT`, puis reprend dans le tour qui reçoit cet événement.
- Utilise exclusivement `$BASE/scripts/send.sh` pour un événement non terminal
  et `$BASE/scripts/done.sh` pour un terminal. N'utilise jamais directement
  Redis et n'écris jamais `FROM:` dans le message.
- Entre agents, renseigne explicitement `TASK_ID`, `CYCLE`, `CORRELATION_ID`,
  `REQUESTER_ID` et `OWNER_ID`. Pour `MESSAGE_EVENT=DISPATCH`, renseigne aussi
  `EXPECTED_EVENT`. L'enveloppe fait foi ; n'infère aucune métadonnée du texte.
- Hérite sans les réécrire de `TASK_ID`, `CYCLE`, `CORRELATION_ID` et
  `REQUESTER_ID`. Un nouveau dispatch peut changer `OWNER_ID` et `TARGET`, mais
  conserve le demandeur initial.
- `send.sh` n'acquitte pas un travail : `DELIVERED` signifie seulement que la
  session cible existe ; `ORPHANED` signifie que le message est persisté mais
  qu'aucune attente active ne doit commencer.
- Émets exactement un terminal avec `done.sh`. Un ACK de réception est
  non-terminal et ne répond jamais à `DONE`, `BLOCKED`, `ERROR`,
  `INFO_REQUIRED`, `ARTIFACT_READY`, `CONCLUSION`, `ARBITRAGE`,
  `PROTOCOL_ERROR` ou `PROMPT_RELOADED`.
- Ignore pour toute transition un événement dupliqué, tardif, d'un autre cycle
  ou d'une autre corrélation. Signale une enveloppe invalide avec
  `PROTOCOL_ERROR` ; n'invente pas les champs manquants.
- Les décisions reposent sur les hard gates, critères d'acceptation et preuves
  durables (`ARTIFACT`, `HASH`, tests). Un score seul n'est jamais terminal.
- Conserve l'état transactionnel sous `pool-requests/state/`, pas seulement en
  mémoire. Archive le paquet de preuves accepté avant de clôturer.
- Dans un triangle `NNN`, tout agent `NNN-YZZ` autre que `NNN-1ZZ` exécute
  `$BASE/scripts/report-master.sh` après chaque travail réel et après un prompt
  direct de l'utilisateur. Un contrôle, terminal reçu, doublon ou rapport de
  supervision n'ouvre aucune obligation et ne reçoit aucun rapport. Si un
  autre demandeur existe,
  livre d'abord sa réponse corrélée puis publie séparément le `MASTER_REPORT`.
  Une réponse dans le TUI n'est pas un envoi. Le script calcule la cible :
  n'inscris aucun identifiant d'exemple en dur. Pour `BLOCKED` ou
  `INFO_REQUIRED`, le publisher partage l'identité de décision du tour avec
  `send.sh`/`done.sh` : il ne produit qu'un `DECISION_REQUIRED` et ne réveille
  le Master qu'une fois. N'envoie jamais de copie manuelle supplémentaire du
  même blocage.
"""
    if "master" in sample or re.search(r"-1\d\d-system\.md$", path.name):
        body += """
- Le Master possède une seule attente active par corrélation et connaît
  `TARGET` et `EXPECTED_EVENT`. Il ne traite pas `ORPHANED` comme accepté,
  dégrade explicitement si un rôle est indisponible et ne fait jamais parler
  l'Observer à la place de l'Observer.
"""
    if "observer" in sample or "tester" in sample or re.search(r"-5\d\d-system\.md$", path.name):
        body += """
- L'Observer publie son propre verdict canonique avec les preuves observées ;
  son identité ne peut pas être simulée par le Master ou le Developer.
"""
    return f"\n\n{COMMUNICATION_MARKER}\n\n{body.strip()}\n"


def user_authority_contract():
    """L'utilisateur fixe le résultat et les choix explicites à exécuter."""
    return f"""

{USER_AUTHORITY_MARKER}

L'utilisateur est l'autorité décisionnelle finale. Exécute toute décision
explicite et récente conformément à ses termes : ne lui substitue ni une autre
solution, ni une autre méthode, ni un autre périmètre au motif qu'ils seraient
préférables. Tu peux signaler un risque et proposer des options, mais tu ne
choisis pas à sa place.

Si une contrainte réelle de sécurité, d'intégrité ou de faisabilité empêche
l'exécution exacte, démontre précisément le blocage et demande une nouvelle
décision. Hors de ce cas, la décision utilisateur est exécutoire et doit être
menée jusqu'au résultat vérifié.
"""


def dev_test_orchestration_contract(path, text):
    """Sépare production du code et validation indépendante dans chaque projet."""
    title = next((line.lower() for line in text.splitlines()
                  if line.startswith("# ")), "")
    sample = f"{path.parent.name.lower()} {path.name.lower()} {title}"
    is_master = "master" in sample or bool(
        re.search(r"-1\d\d-system\.md$", path.name))
    is_developer = "developer" in sample or "dévelop" in sample or bool(
        re.search(r"-3\d\d-system\.md$", path.name))
    is_tester = ("observer" in sample or "tester" in sample
                 or bool(re.search(r"-5\d\d-system\.md$", path.name)))
    is_curator = "curator" in sample or bool(
        re.search(r"-7\d\d-system\.md$", path.name))
    is_coach = "coach" in sample or bool(
        re.search(r"-8\d\d-system\.md$", path.name))
    is_architect = ("architect" in sample
                    or bool(re.search(r"-9\d\d-system\.md$", path.name)))

    if is_creator(path) or is_architect:
        body = """
Tout projet ou triangle généré inscrit explicitement dans son Master `1XX` le
cycle suivant : dispatcher l'implémentation du code à un `3XX`, dispatcher la
conception et l'écriture des tests à un `5XX`, puis faire exécuter ces tests par
le `5XX` sur le code réellement livré par le `3XX`. La préparation des tests
peut commencer en parallèle du développement ; le verdict final attend
obligatoirement la livraison du code.

Le prompt généré du `3XX` le rend exclusivement propriétaire de
l'implémentation : il ne conçoit, n'écrit ni n'exécute les tests et ne lance
aucune phase de validation. Le prompt généré du `5XX` le rend seul propriétaire
des tests indépendants dérivés de la demande utilisateur, de leur écriture, de
leur exécution, du diagnostic et des re-tests. Le `1XX` ne clôture jamais
sur la seule déclaration du `3XX` et organise `3XX corrige → 5XX reteste`
jusqu'à verdict conforme ou arbitrage utilisateur.

Après un verdict conforme du `5XX`, le Master dispatche en parallèle `7XX`,
`8XX` et `9XX` : `7XX` consolide le contexte et les connaissances utiles,
`8XX` analyse les améliorations de méthode, `9XX` audite les impacts
structurels et les prompts. Le Master attend leurs trois terminaux et consolide
leurs résultats. Cette phase ne rouvre pas automatiquement le code validé et
aucune recommandation ne remplace une décision explicite de l'utilisateur.
"""
    elif is_master:
        body = """
Pour toute tâche qui développe ou modifie du code :

1. formalise la décision utilisateur et ses critères d'acceptation sans en
   changer la solution, la méthode ou le périmètre ;
2. dispatche l'implémentation à un `3XX` avec un terminal de livraison attendu ;
3. dispatche à un `5XX` la conception et l'écriture de tests indépendants ; ce
   travail peut avancer en parallèle du développement ;
4. après livraison du `3XX`, dispatche au `5XX` l'exécution des tests sur cette
   version exacte du code ;
5. sur échec, retourne au `3XX` les défauts et preuves du `5XX`, puis exige un
   nouveau passage du `5XX` après correction ;
6. après verdict conforme du `5XX`, dispatche `7XX`, `8XX` et `9XX` en parallèle
   avec trois événements terminaux distincts ;
7. attends leurs trois retours, puis consolide : contexte/connaissance du `7XX`,
   amélioration de méthode du `8XX`, impacts structurels/prompts du `9XX` ;
8. clôture seulement après réception du code, des tests, du verdict conforme et
   des trois terminaux post-validation.

Le `1XX` ne développe pas le code à la place du `3XX`, ne valide pas à la place
du `5XX` et ne demande aucune phase de test au Developer. Les avis
`7XX/8XX/9XX` ne rouvrent pas automatiquement le code
validé : toute divergence avec une décision utilisateur lui est soumise.
"""
    elif is_developer:
        body = """
Tu es exclusivement responsable de l'implémentation demandée. Pour préserver
le budget du rôle `3XX`, ne conçois, n'écris ni n'exécute les tests et ne lance
aucune phase ou suite de validation. Livre rapidement au `1XX` le code, les
fichiers modifiés et les limites connues. Corrige les défauts factuels transmis
par le `1XX`, puis livre une nouvelle version testable au `5XX`.
"""
    elif is_tester:
        body = """
Tu es seul responsable de toutes les phases de test. Dérive les tests de la demande
utilisateur, de ses critères d'acceptation et des risques observables, pas
seulement des cas suggérés par le `3XX`. Tu peux concevoir et écrire les tests
pendant le développement, mais tu rends le verdict final uniquement après les
avoir exécutés sur la version exacte livrée par le `3XX`. Fournis au `1XX` les
commandes, résultats, diagnostics et défauts reproductibles ; après correction,
reteste. Aucun test ne doit être délégué au `3XX`.
"""
    elif is_curator:
        body = """
Après le verdict conforme du `5XX`, consolide le contexte, les connaissances et
les sources utiles révélés par le cycle. Travaille en parallèle des `8XX` et
`9XX`, sans modifier leur périmètre. Livre au `1XX` un delta traçable ; ne
rouvre pas le code validé et ne remplace aucune décision utilisateur.
"""
    elif is_coach:
        body = """
Après le verdict conforme du `5XX`, analyse les améliorations de méthode utiles
au prochain cycle. Travaille en parallèle des `7XX` et `9XX`. Une amélioration
facultative ne bloque pas la livraison, ne rouvre pas le code validé et ne
remplace aucune décision utilisateur.
"""
    else:
        return ""
    return f"\n\n{DEV_TEST_ORCHESTRATION_MARKER}\n\n{body.strip()}\n"


def periodic_optimizer_contract(path):
    if not re.search(r"-2\d\d-system\.md$", path.name):
        return ""
    return f"""

{PERIODIC_OPTIMIZER_MARKER}

Le créateur écrit ta tâche 6 h sous `NNN-2XX_360.prompt.suspended`. Au tir
activé par l'opérateur, collecte l'état réel. Si ton Master n'a aucun prompt
planifié, construis depuis l'objectif utilisateur et l'état durable un premier
pilotage idempotent, puis crée uniquement `NNN-1XX_120.prompt.suspended` via
`contradictor.sh revise-prompt NNN`. Ne l'active jamais.

Si le prompt Master existe, améliore uniquement son texte via
`contradictor.sh revise-prompt NNN`. Ne change aucun nom, période ou statut,
aucun autre fichier crontab ou prompt d'agent. Aucun `DONE`, transition ou
dispatch. Si aucun gain concret n'est possible : `NOOP`, silence total.
"""


def block(path, text):
    finality = purpose(path, text)
    result = f"""

## Priorité au résultat

**Finalité :** {finality}.

Le processus, les rôles, la mémoire, les enveloppes et les scripts sont des
moyens. Applique-les silencieusement ; leur respect n'est pas un livrable.
Considère la mission réussie seulement lorsque le résultat utile existe,
fonctionne et répond à l'intention. Vérifie-le en proportion du risque.

Dans la réponse, présente dans cet ordre : résultat obtenu, preuves utiles,
limites éventuelles. Ne raconte le processus que s'il affecte le résultat ou
nécessite une décision. Les frontières fortes de sécurité restent absolues.
"""
    if is_creator(path):
        result += """

## Contrat de création résultat-first

Chaque agent généré commence par sa finalité métier et des critères observables
de réussite. Son processus, sa mémoire, ses enveloppes et ses scripts sont des
moyens appliqués silencieusement. Son contrat de réponse impose : résultat
obtenu, preuves utiles, limites éventuelles.

Ne génère jamais un agent dont la réussite se limite à suivre, raconter ou
confirmer son workflow. Les frontières fortes restent absolues.

Chaque x45/z21 généré applique le contrat de livraison piloté par les preuves :
les hard gates et critères obligatoires gouvernent la livraison, jamais un seuil
de score mou. Le Master intègre et clôture ; l'Observer rend un verdict canonique
et sépare blocants Dev, actions d'intégration et améliorations facultatives ; le
Coach améliore le prochain cycle sans bloquer celui qui est livrable.
"""
    return (result + user_authority_contract()
            + delivery_contract(path, text)
            + dev_test_orchestration_contract(path, text)
            + contradictor_scope_contract(path, text)
            + communication_contract(path, text))


def insert(text, addition):
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("# "):
            return "".join(lines[:index + 1]) + addition + "".join(lines[index + 1:])
    return addition.lstrip("\n") + "\n" + text


def refresh(text, addition):
    if MARKER not in text:
        return insert(text, addition)
    start = text.index(MARKER)
    next_heading = text.find("\n## ", start + len(MARKER))
    if next_heading < 0:
        return text[:start] + addition.strip("\n") + "\n"
    return text[:start] + addition.strip("\n") + "\n" + text[next_heading:]


def remove_sections(text, heading):
    """Retire toutes les occurrences d'une section générée avant régénération."""
    while heading in text:
        start = text.index(heading)
        if start >= 2 and text[start - 2:start] == "\n\n":
            start -= 2
        next_heading = text.find("\n## ", start + len(heading))
        if next_heading < 0:
            text = text[:start].rstrip() + "\n"
        else:
            text = text[:start].rstrip() + "\n\n" + text[next_heading + 1:]
    return text


def candidates(base):
    selected = set()
    for root in (base / "prompts", base / "examples"):
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            if path.is_symlink() or not path.is_file():
                continue
            if "removed" in path.parts:
                continue
            name = path.name
            if (name.endswith("-system.md") or name == "system.md"
                    or (root.name == "examples" and "prompts" in path.parts
                        and not (name.endswith("-memory.md")
                                 or name.endswith("-methodology.md")
                                 or name in {"memory.md", "methodology.md", "archi.md"}))
                    or (root.name == "prompts" and path.parent.name == "000-hub-master"
                        and name.endswith(".md"))):
                selected.add(path)
    templates = base / "templates"
    if templates.exists():
        template_roots = (templates / "prompts", templates / "x45" / "prompts")
        for template_root in template_roots:
            if not template_root.exists():
                continue
            for path in template_root.rglob("*"):
                if path.is_file() and not path.is_symlink() and (
                        path.name.endswith("-system.md") or path.name == "system.md"
                        or path.name.endswith(".md.template")):
                    selected.add(path)
    return sorted(selected)


def migrate(base, backup=True, refresh_existing=False, check=False):
    changed = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = base / "removed" / "rebalance-prompts" / stamp
    for path in candidates(base):
        text = path.read_text(errors="replace")
        needs_creator_contract = is_creator(path) and CREATOR_MARKER not in text
        needs_delivery_contract = bool(delivery_contract(path, text)) and DELIVERY_MARKER not in text
        needs_contradictor_scope = (
            bool(contradictor_scope_contract(path, text))
            and CONTRADICTOR_SCOPE_MARKER not in text
        )
        needs_communication_contract = COMMUNICATION_MARKER not in text
        needs_user_authority = USER_AUTHORITY_MARKER not in text
        needs_dev_test_orchestration = (
            bool(dev_test_orchestration_contract(path, text))
            and DEV_TEST_ORCHESTRATION_MARKER not in text
        )
        needs_periodic_optimizer = (
            bool(periodic_optimizer_contract(path))
            and PERIODIC_OPTIMIZER_MARKER not in text
        )
        if (MARKER in text and not refresh_existing and not needs_creator_contract
                and not needs_delivery_contract and not needs_contradictor_scope
                and not needs_communication_contract and not needs_user_authority
                and not needs_dev_test_orchestration
                and not needs_periodic_optimizer):
            continue
        if MARKER in text:
            if refresh_existing:
                cleaned = remove_sections(text, DELIVERY_MARKER)
                cleaned = remove_sections(cleaned, CONTRADICTOR_SCOPE_MARKER)
                cleaned = remove_sections(cleaned, LEGACY_CONTRADICTOR_SCOPE_MARKER)
                cleaned = remove_sections(cleaned, COMMUNICATION_MARKER)
                cleaned = remove_sections(
                    cleaned, PREVIOUS_COMMUNICATION_MARKER)
                cleaned = remove_sections(
                    cleaned, LEGACY_COMMUNICATION_MARKER)
                cleaned = remove_sections(cleaned, USER_AUTHORITY_MARKER)
                cleaned = remove_sections(
                    cleaned, DEV_TEST_ORCHESTRATION_MARKER)
                cleaned = remove_sections(
                    cleaned, LEGACY_DEV_TEST_ORCHESTRATION_MARKER)
                desired = refresh(cleaned, block(path, cleaned))
            else:
                desired = text
            if needs_creator_contract:
                desired = insert(desired, block(path, text))
            if needs_delivery_contract and DELIVERY_MARKER not in desired:
                desired = insert(desired, delivery_contract(path, text))
            if needs_contradictor_scope and CONTRADICTOR_SCOPE_MARKER not in desired:
                desired = remove_sections(
                    desired, LEGACY_CONTRADICTOR_SCOPE_MARKER)
                desired = insert(desired, contradictor_scope_contract(path, text))
            if needs_communication_contract and COMMUNICATION_MARKER not in desired:
                desired = remove_sections(
                    desired, LEGACY_COMMUNICATION_MARKER)
                desired = remove_sections(
                    desired, PREVIOUS_COMMUNICATION_MARKER)
                desired = insert(desired, communication_contract(path, text))
            if needs_user_authority and USER_AUTHORITY_MARKER not in desired:
                desired = insert(desired, user_authority_contract())
            if (needs_dev_test_orchestration
                    and DEV_TEST_ORCHESTRATION_MARKER not in desired):
                desired = remove_sections(
                    desired, LEGACY_DEV_TEST_ORCHESTRATION_MARKER)
                desired = insert(
                    desired, dev_test_orchestration_contract(path, text))
            if needs_periodic_optimizer and PERIODIC_OPTIMIZER_MARKER not in desired:
                desired = insert(desired, periodic_optimizer_contract(path))
        else:
            desired = insert(text, block(path, text))
            if needs_periodic_optimizer:
                desired = insert(desired, periodic_optimizer_contract(path))
        if desired == text:
            continue
        if check:
            changed.append(path)
            continue
        if backup:
            relative = path.relative_to(base)
            destination = backup_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        path.write_text(desired)
        changed.append(path)

    methodology_candidates = []
    for root in (base / "prompts", base / "examples"):
        if not root.exists():
            continue
        methodology_candidates.extend(
            path for path in root.rglob("*-2??-methodology.md")
            if path.is_file() and not path.is_symlink() and "removed" not in path.parts
        )
    template_root = base / "templates" / "x45" / "prompts"
    if template_root.exists():
        methodology_candidates.extend(
            path for path in template_root.rglob("methodology.md")
            if path.is_file() and path.parent.name in {"contradictor-2xx", "echo-200"}
        )
    for path in sorted(set(methodology_candidates)):
        text = path.read_text(errors="replace")
        needs_method = CONTRADICTOR_METHOD_MARKER not in text
        needs_fallback = CONTRADICTOR_FALLBACK_MARKER not in text
        needs_periodic = PERIODIC_OPTIMIZER_MARKER not in text
        if not needs_method and not needs_fallback and not needs_periodic:
            continue
        if check:
            changed.append(path)
            continue
        if backup:
            relative = path.relative_to(base)
            destination = backup_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        if needs_method:
            addition = contradictor_methodology_contract()
        elif needs_fallback:
            addition = contradictor_fallback_contract()
        else:
            addition = periodic_optimizer_contract(
                Path(path.parent, "placeholder-200-system.md"))
        if needs_periodic and PERIODIC_OPTIMIZER_MARKER not in addition:
            addition += periodic_optimizer_contract(
                Path(path.parent, "placeholder-200-system.md"))
        path.write_text(insert(text, addition))
        changed.append(path)

    # Une tâche 2XX est créée suspendue uniquement si son Master possède déjà
    # un prompt planifié. L'activation reste exclusivement opérateur.
    crontab = base / "crontab"
    if crontab.is_dir():
        for directory in sorted((base / "prompts").glob("[0-9][0-9][0-9]*")):
            match = re.match(r"^(\d{3})", directory.name)
            if not match or not directory.is_dir():
                continue
            triangle = match.group(1)
            masters = sorted(directory.glob(f"{triangle}-1??-system.md"))
            contradictors = sorted(directory.glob(f"{triangle}-2??-system.md"))
            if len(masters) != 1 or len(contradictors) != 1:
                continue
            master = masters[0].name.removesuffix("-system.md")
            contradictor = contradictors[0].name.removesuffix("-system.md")
            active = crontab / f"{contradictor}_360.prompt"
            suspended = crontab / f"{contradictor}_360.prompt.suspended"
            if active.exists() or suspended.exists():
                continue
            if check:
                changed.append(suspended)
                continue
            suspended.write_text(
                f"Collecte une fois l'état réel du triangle {triangle}. Si "
                f"{master} n'a aucun prompt planifié, crée son pilotage 120 min "
                "désactivé via revise-prompt ; sinon améliore-le via "
                "revise-prompt. Ne change ni objectifs, nom, période ou statut. "
                "NOOP et silence total si aucun gain concret.\n"
            )
            changed.append(suspended)
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="liste les prompts à migrer sans les modifier")
    args = parser.parse_args()
    changed = migrate(args.base.resolve(), not args.no_backup,
                      args.refresh, args.check)
    for path in changed:
        print(path.relative_to(args.base.resolve()))
    print(f"updated={len(changed)}")


if __name__ == "__main__":
    main()
