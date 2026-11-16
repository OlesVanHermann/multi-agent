# Tâche s02-stats-cli (niveau 2)

Dans ton répertoire de travail projet, crée le fichier `bench_work/stats.py` :
un outil en ligne de commande qui lit des nombres sur l'entrée standard
(un par ligne) et affiche des statistiques.

## Comportement attendu

Exécuté via `python3 bench_work/stats.py` :

- Lit stdin ligne par ligne ; chaque ligne non vide est un nombre
  (entier ou décimal). Les lignes vides sont ignorées.
- Une ligne non numérique → message `erreur: ligne invalide: <contenu>`
  sur stderr et code de sortie `2`, sans rien afficher sur stdout.
- Aucune donnée (entrée vide) → message `erreur: aucune donnee` sur stderr,
  code de sortie `1`.
- Sinon, affiche sur stdout exactement 4 lignes, dans cet ordre, valeurs
  formatées avec 2 décimales :

```
min=<valeur>
max=<valeur>
mean=<moyenne>
median=<mediane>
```

## Exemple

Entrée `1\n2\n3\n4\n` → sortie :

```
min=1.00
max=4.00
mean=2.50
median=2.50
```

Code de sortie `0`.

## Périmètre

Uniquement `bench_work/stats.py`. Bibliothèque standard uniquement.
