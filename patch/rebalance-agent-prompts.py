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
        return ("améliorer la compréhension et la décision du 1XX par une "
                "conclusion factuelle, concise et actionnable")
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
    return result + delivery_contract(path, text)


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
        if MARKER in text and not refresh_existing and not needs_creator_contract and not needs_delivery_contract:
            continue
        if MARKER in text:
            if refresh_existing:
                cleaned = remove_sections(text, DELIVERY_MARKER)
                desired = refresh(cleaned, block(path, cleaned))
            else:
                desired = text
            if needs_creator_contract:
                desired = insert(desired, block(path, text))
            elif needs_delivery_contract:
                desired = insert(desired, delivery_contract(path, text))
        else:
            desired = insert(text, block(path, text))
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
