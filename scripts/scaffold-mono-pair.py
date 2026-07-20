#!/usr/bin/env python3
"""Transforme un mono NNN en paire principal NNN-1XX + Contradictor NNN-2XX."""

import argparse
import shutil
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def default_suffixes(prefix):
    """Conserve les deux derniers chiffres du groupe: 345 -> 145/245."""
    if not prefix.isdigit() or len(prefix) != 3 or prefix == "000":
        raise ValueError("préfixe NNN non protégé (001..999)")
    tail = prefix[1:]
    return f"1{tail}", f"2{tail}"


def archive(path, removed):
    if path.exists() or path.is_symlink():
        removed.mkdir(parents=True, exist_ok=True)
        destination = removed / f"{int(time.time() * 1000)}-{path.name}"
        path.replace(destination)
        return destination
    return None


def scaffold(base, prefix, main_suffix, contradictor_suffix, directory_name,
             contradictor_model, contradictor_login,
             main_model="fable-5", main_login="login1a"):
    prompts = base / "prompts"
    directory = prompts / directory_name
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    removed = base / "removed" / "scaffold-mono-pair"
    main_id = f"{prefix}-{main_suffix}"
    contradictor_id = f"{prefix}-{contradictor_suffix}"

    canonical_legacy = directory / f"{directory_name}.md"
    if canonical_legacy.exists():
        # Les créateurs 160/170 portent aussi des documents auxiliaires
        # préfixés par leur ID; seul le prompt portant le nom du répertoire
        # constitue le principal historique.
        legacy = [canonical_legacy]
    else:
        legacy = sorted(directory.glob(f"{prefix}-*.md"))
        legacy = [path for path in legacy if path.name not in
                  {f"{main_id}.md", f"{contradictor_id}.md"}]
    main_system = directory / f"{main_id}-system.md"
    legacy_stem = legacy[0].stem if len(legacy) == 1 else None
    if not main_system.exists():
        if len(legacy) != 1:
            raise ValueError("un unique prompt mono historique est requis")
        source = archive(legacy[0], removed)
        shutil.copy2(source, main_system)

    main_memory = directory / f"{main_id}-memory.md"
    main_methodology = directory / f"{main_id}-methodology.md"
    if not main_memory.exists():
        main_memory.write_text(
            f"# Mémoire {main_id}\n\nContexte actif du principal. L'état physique "
            "et la demande utilisateur récente priment sur cette mémoire.\n")
    if not main_methodology.exists():
        main_methodology.write_text(
            f"# Méthodologie {main_id}\n\nExécuter la demande, produire des preuves "
            "vérifiables, puis publier exactement un événement terminal.\n")

    template_root = base / "templates" / "x45" / "prompts" / "contradictor-2xx"
    for kind in ("system", "memory", "methodology"):
        text = ((template_root / f"{kind}.md").read_text()
                .replace("2XX", contradictor_suffix)
                .replace("__TRIANGLE__", prefix)
                .replace("3XX-1XX", main_id)
                .replace("__MAIN__", main_id)
                .replace("__CONTRADICTOR__", contradictor_id))
        destination = directory / f"{contradictor_id}-{kind}.md"
        archive(destination, removed)
        destination.write_text(text)
    for agent_id in (main_id, contradictor_id):
        entry = directory / f"{agent_id}.md"
        archive(entry, removed)
        entry.symlink_to(Path("..") / "AGENT.md")
    (directory / "contradictor.target").write_text(main_id + "\n")

    for agent_id in (main_id, contradictor_id):
        for ext in ("login", "model", "effort"):
            old = directory / f"{legacy_stem}.{ext}" if legacy_stem else directory / f"{prefix}.{ext}"
            destination = directory / f"{agent_id}.{ext}"
            if agent_id == main_id and old.exists() and not destination.exists():
                # Lire avant archivage: un lien relatif déplacé dans removed/
                # ne résout plus vers prompts/ et devient donc illisible.
                value = old.read_text()
                archive(old, removed)
                destination.write_text(value)
    legacy_history = directory / f"{legacy_stem}.history" if legacy_stem else None
    main_history = directory / f"{main_id}.history"
    if legacy_history and legacy_history.exists() and not main_history.exists():
        source = archive(legacy_history, removed)
        shutil.copy2(source, main_history)
    main_history.touch(exist_ok=True)
    (directory / f"{contradictor_id}.history").touch(exist_ok=True)
    # Affectation canonique: le principal raisonne avec Fable, le Contradictor
    # vérifie avec Sol. Les profils suivent obligatoirement le moteur du modèle.
    assignments = (
        (main_id, "model", main_model),
        (main_id, "login", main_login),
        (contradictor_id, "model", contradictor_model),
        (contradictor_id, "login", contradictor_login),
    )
    for agent_id, ext, source in assignments:
        source_path = prompts / f"{source}.{ext}"
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        destination = directory / f"{agent_id}.{ext}"
        archive(destination, removed)
        destination.symlink_to(Path("..") / source_path.name)
    (directory / f"{contradictor_id}.effort").write_text("H\n")
    (directory / f"{main_id}.effort").write_text("H\n")
    # Marqueur de transaction écrit en dernier: sa présence signifie que toute
    # la paire et toutes ses configurations ont été matérialisées avec succès.
    (directory / "mono-pair.json").write_text(
        '{"type":"mono-pair","main":"' + main_id
        + '","contradictor":"' + contradictor_id + '"}\n')
    return main_id, contradictor_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prefix", help="groupe 3XX")
    parser.add_argument("--directory-name", required=True)
    parser.add_argument("--main-suffix", help="slot 1XX (défaut: mêmes dizaines/unités)")
    parser.add_argument("--contradictor-suffix", help="slot 2XX (défaut: mêmes dizaines/unités)")
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--contradictor-model", default="gpt-5-6-sol")
    parser.add_argument("--contradictor-login", default="login3a")
    parser.add_argument("--main-model", default="fable-5")
    parser.add_argument("--main-login", default="login1a")
    args = parser.parse_args()
    try:
        default_main, default_contradictor = default_suffixes(args.prefix)
    except ValueError as exc:
        parser.error(str(exc))
    args.main_suffix = args.main_suffix or default_main
    args.contradictor_suffix = args.contradictor_suffix or default_contradictor
    values = ((args.main_suffix, 100, 199, "main-suffix 1XX"),
              (args.contradictor_suffix, 200, 299, "contradictor-suffix 2XX"))
    for value, low, high, label in values:
        if not value.isdigit() or not low <= int(value) <= high:
            parser.error(label)
    print(scaffold(args.base.resolve(), args.prefix, args.main_suffix,
                   args.contradictor_suffix, args.directory_name,
                   args.contradictor_model, args.contradictor_login,
                   args.main_model, args.main_login))


if __name__ == "__main__":
    main()
