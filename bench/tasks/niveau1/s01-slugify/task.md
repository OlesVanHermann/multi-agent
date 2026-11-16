# Tâche s01-slugify (niveau 1)

Dans ton répertoire de travail projet, crée le fichier `bench_work/slugify.py`
contenant une fonction :

```python
def slugify(text: str) -> str
```

## Comportement attendu

- Convertit en minuscules.
- Remplace les caractères accentués courants du français par leur équivalent
  non accentué (é→e, è→e, ê→e, à→a, â→a, ç→c, î→i, ï→i, ô→o, ù→u, û→u, ë→e).
- Remplace toute séquence de caractères non alphanumériques par un tiret
  unique `-`.
- Supprime les tirets en début et fin de résultat.
- Une chaîne vide ou sans aucun caractère alphanumérique retourne `""`.

## Exemples

- `slugify("Écran d'accueil")` → `"ecran-d-accueil"`
- `slugify("  Hello,  World!  ")` → `"hello-world"`
- `slugify("---")` → `""`

## Périmètre

Uniquement `bench_work/slugify.py`. Pas de dépendance externe
(bibliothèque standard uniquement).
