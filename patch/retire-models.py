#!/usr/bin/env python3
"""Retire du catalogue prompts/ les modèles qui ne sont plus proposés.

Usage: retire-models.py [--check] [--backup DIR] PROMPTS_DIR

  --check  : rapporte ce qui serait retiré sans rien déplacer (dry-run).
  --backup : répertoire de sauvegarde (obligatoire hors --check).

Un modèle REMPLACÉ (REPLACED_MODELS) est d'abord substitué partout dans
prompts/ : les liens vers <ancien>.model / <ancien>.advisor sont repointés
vers <nouveau>.model / <nouveau>.advisor, et les anciens fichiers texte
(override .advisor contenant le nom, .model contenant l'identifiant) sont
réécrits, l'original sauvegardé. Il est ensuite retiré comme les autres.

Un modèle n'est JAMAIS supprimé : il est déplacé dans le répertoire de
sauvegarde de l'upgrade. Un modèle encore référencé par un lien symbolique
de prompts/ (override d'agent, default.model, catalogue .advisor…) est
conservé et signalé MANUAL : le retirer ferait démarrer l'agent, sans erreur
visible, sur le modèle par défaut du CLI. Idempotent : un modèle déjà absent
est ignoré.

Codes retour : 0 = OK (MANUAL compris, non bloquant), 2 = usage.
"""
import os
import shutil
import sys

# Remplacés en v3.2.30 (décision opérateur, 2026-11-10) : ancien → nouveau.
REPLACED_MODELS = {
    "fable-5-1": "fable-5-2",
}

# Retirés en v3.2.28 (décision opérateur, 2026-10-07).
RETIRED_MODELS = (
    "fable-5.model",
    "gpt-5-3-codex-spark.model",
    "gpt-5-4-mini.model",
    "gpt-5-4.model",
    "gpt-5-5.model",
    "opus-4-5.model",
    "opus-4-6.model",
    "opus-4-7.model",
    "opus-4-8.model",
    "sonnet-4-5.model",
    "sonnet-4-6.model",
    # Retirés en v3.2.30, remplacés (REPLACED_MODELS). L'advisor avant le
    # .model : le catalogue <nom>.advisor est le dernier lien vers <nom>.model.
    "fable-5-1.advisor",
    "fable-5-1.model",
)


def symlink_references(prompts_dir):
    """{chemin absolu de la cible: [liens]} pour tous les liens de prompts/."""
    refs = {}
    for root, dirs, files in os.walk(prompts_dir, followlinks=False):
        for name in dirs + files:
            link = os.path.join(root, name)
            if not os.path.islink(link):
                continue
            target = os.path.normpath(os.path.join(root, os.readlink(link)))
            refs.setdefault(target, []).append(os.path.relpath(link, prompts_dir))
    return refs


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _backup(prompts_dir, backup_dir, path):
    """Copie l'original (lien ou fichier) sous <backup>/replaced/<chemin>."""
    dest = os.path.join(backup_dir, "replaced", os.path.relpath(path, prompts_dir))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.lexists(dest):
        return
    if os.path.islink(path):
        os.symlink(os.readlink(path), dest)
    else:
        shutil.copy2(path, dest)


def replace(prompts_dir, backup_dir, check):
    """Substitue les modèles remplacés. Retourne (replaced, manual, liens).

    `liens` : chemins relatifs des liens repointés, pour que le retrait qui
    suit ne les compte plus comme références en dry-run.
    """
    replaced = manual = 0
    links = set()
    for old, new in REPLACED_MODELS.items():
        catalog = {os.path.join(prompts_dir, old + ext) for ext in (".model", ".advisor")}
        old_ident = _read_text(os.path.join(prompts_dir, old + ".model"))
        new_ident = _read_text(os.path.join(prompts_dir, new + ".model"))
        for root, dirs, files in os.walk(prompts_dir, followlinks=False):
            for name in sorted(dirs + files):
                path = os.path.join(root, name)
                if path in catalog:
                    continue
                rel = os.path.relpath(path, prompts_dir)
                if os.path.islink(path):
                    text = os.readlink(path)
                    target = os.path.normpath(os.path.join(root, text))
                    ext = next((e for e in (".model", ".advisor")
                                if target == os.path.join(prompts_dir, old + e)), None)
                    if ext is None:
                        continue
                    new_text = os.path.join(os.path.dirname(text), new + ext)
                    if not check and not os.path.lexists(
                            os.path.join(prompts_dir, new + ext)):
                        manual += 1
                        print(f"[MANUAL] prompts/{rel} → {text} : prompts/{new}{ext} absent")
                        continue
                    replaced += 1
                    links.add(rel)
                    if check:
                        print(f"[REPLACE] prompts/{rel} → {new_text} (au lieu de {text})")
                        continue
                    _backup(prompts_dir, backup_dir, path)
                    tmp = path + ".replace-tmp"
                    os.symlink(new_text, tmp)
                    os.replace(tmp, path)
                    print(f"[OK]     prompts/{rel} → {new_text}")
                    continue
                if not os.path.isfile(path):
                    continue
                if name.endswith(".advisor") and _read_text(path) == old:
                    ext, value = ".advisor", new
                elif name.endswith(".model") and old_ident and _read_text(path) == old_ident:
                    ext, value = ".model", new_ident
                else:
                    continue
                if not check and not (value and os.path.lexists(
                        os.path.join(prompts_dir, new + ext))):
                    manual += 1
                    print(f"[MANUAL] prompts/{rel} ({old}) : prompts/{new}{ext} absent")
                    continue
                replaced += 1
                if check:
                    print(f"[REPLACE] prompts/{rel} : {old} → {new}")
                    continue
                _backup(prompts_dir, backup_dir, path)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(value + "\n")
                print(f"[OK]     prompts/{rel} : {old} → {new}")
    return replaced, manual, links


def retire(prompts_dir, backup_dir, check):
    prompts_dir = os.path.abspath(prompts_dir)
    replaced, manual, gone = replace(prompts_dir, backup_dir, check)
    retired = 0
    for name in RETIRED_MODELS:
        path = os.path.join(prompts_dir, name)
        if not (os.path.lexists(path)):
            continue
        # Références recalculées à chaque modèle : retirer <nom>.advisor libère
        # <nom>.model. En dry-run, `gone` tient lieu des liens repointés et des
        # entrées déjà retirées.
        refs = symlink_references(prompts_dir)
        users = sorted(u for u in refs.get(path, []) if u not in gone)
        if users:
            manual += 1
            print(f"[MANUAL] prompts/{name} conservé : encore référencé par "
                  + ", ".join(users))
            continue
        retired += 1
        gone.add(name)
        if check:
            print(f"[RETIRE] prompts/{name} (déplacé dans la sauvegarde)")
            continue
        os.makedirs(backup_dir, exist_ok=True)
        shutil.move(path, os.path.join(backup_dir, name))
        print(f"[OK]     prompts/{name} → {os.path.join(backup_dir, name)}")
    print(f"replaced={replaced} retired={retired} manual={manual}")


def main(argv):
    args = list(argv)
    check = "--check" in args
    if check:
        args.remove("--check")
    backup_dir = None
    if "--backup" in args:
        i = args.index("--backup")
        if i + 1 >= len(args):
            print(__doc__, file=sys.stderr)
            return 2
        backup_dir = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1 or not os.path.isdir(args[0]) or (not check and not backup_dir):
        print(__doc__, file=sys.stderr)
        return 2
    retire(args[0], backup_dir, check)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
