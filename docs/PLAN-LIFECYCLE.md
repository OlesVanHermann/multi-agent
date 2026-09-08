# Cycle de vie horodaté des plans

Cette convention concerne uniquement les plans et leurs journaux. Elle ne
s'applique jamais aux fichiers de prompts.

## Identité du plan

À la création, le plan reçoit un identifiant UTC immuable :

```text
20260726T125656150056Z-import-csv.md
```

Le même nom est conservé pendant tout le cycle :

```text
plan-TODO/20260726T125656150056Z-import-csv.md
plan-DOING/20260726T125656150056Z-import-csv.md
plan-DONE/20260726T125656150056Z-import-csv.md
```

Il est interdit d'ajouter un nouvel horodatage au nom lors du passage à
`DOING` ou `DONE` : le préfixe initial est l'identité stable utilisée par les
corrélations, rapports, artefacts et tests.

## Horodatages des transitions

Le front matter du plan conserve :

```yaml
plan_id: 20260726T125656150056Z-import-csv
created_at: 2026-07-26T12:56:56.150056Z
started_at: null
completed_at: null
status: TODO
```

- création : renseigner `created_at` et `status: TODO` ;
- exécution : renseigner `started_at` et `status: DOING` avant le déplacement ;
- archivage : renseigner `completed_at` et `status: DONE` avant le déplacement.

Une transition non mesurée utilise `null`, jamais une heure reconstruite après
coup.

## Journal immuable

Chaque transition ajoute une ligne à `logs/plan-lifecycle.tsv` :

```text
timestamp	plan_id	transition	duration_seconds	status	path
2026-07-26T12:56:56.150056Z	20260726T125656150056Z-import-csv	CREATED	0	TODO	plans/app/plan-TODO/...
```

Les rapports ou snapshots de transition peuvent être archivés sous
`logs/plans/<YYYYMMDDTHHMMSSffffffZ>-<plan_id>-<transition>.md`.

