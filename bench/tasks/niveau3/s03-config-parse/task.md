# Tâche s03-config-parse (niveau 3)

Dans ton répertoire de travail projet, crée le fichier
`bench_work/config_parse.py` contenant une fonction :

```python
def parse_config(text: str) -> dict
```

Elle analyse un format de configuration de type INI simplifié et retourne
un dictionnaire `{section: {clef: valeur}}`.

## Règles du format

- Une section est déclarée par une ligne `[nom]`. Les clefs qui suivent lui
  appartiennent, jusqu'à la section suivante.
- Une affectation est `clef = valeur` (espaces autour du `=` ignorés,
  espaces en début/fin de ligne ignorés).
- Les lignes vides sont ignorées.
- Les commentaires commencent par `#` ou `;` en début de ligne (après les
  espaces éventuels) et sont ignorés.
- Une valeur peut être vide (`clef =`) → chaîne vide `""`.
- Si la même clef apparaît plusieurs fois dans la même section, les valeurs
  sont cumulées dans une liste, dans l'ordre du fichier (une clef vue une
  seule fois reste une chaîne simple).
- Des affectations avant toute section vont dans la section `""` (chaîne
  vide).
- Une section déclarée deux fois fusionne ses clefs (le cumul en liste
  s'applique aussi à travers les deux blocs).

## Erreurs

- Ligne ni vide, ni commentaire, ni section, ni affectation (pas de `=`) →
  lever `ValueError` avec le numéro de ligne (1-indexé) dans le message,
  format : `ligne <n>: syntaxe invalide`.
- Section non fermée `[nom` → même `ValueError`.

## Exemple

```ini
# global
timeout = 30

[redis]
host = localhost
port = 6379
tag = a
tag = b
```

→

```python
{"": {"timeout": "30"},
 "redis": {"host": "localhost", "port": "6379", "tag": ["a", "b"]}}
```

## Périmètre

Uniquement `bench_work/config_parse.py`. Bibliothèque standard uniquement
(sans `configparser` — le comportement demandé diffère).
