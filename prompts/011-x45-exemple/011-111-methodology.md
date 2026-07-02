# 011-111 Methodology — Cycle x45

## Principe autonome
Le Master gère le cycle COMPLET sans demander confirmation.
JAMAIS "je continue ?" — FAIRE.

## Phase A — Préparation

```bash
# Prendre la prochaine tâche
find $BASE/project/plan-DOING -name "*.md" -type f | head -1
# Si vide : prendre depuis plan-TODO (ordre alphabétique)
find $BASE/project/plan-TODO -name "*.md" -type f | sort | head -1
# Déplacer en DOING
mv plan-TODO/{CAT}/{task}.md plan-DOING/{CAT}/{task}.md
```

## Phase B — Cycle itératif

### Step 1 : Curator (011-711)
```bash
$BASE/scripts/send.sh 011-711 "curator — {TASK_ID} cycle {N}"
```
Attendre `FROM:011-711|DONE` (timeout 10 min).

### Step 2 : Dev (011-011)
```bash
$BASE/scripts/send.sh 011-011 "start — {TASK_ID} cycle {N}"
```
Attendre `FROM:011-011|DONE` (timeout 15 min).

### Step 3 : Observer (011-511)
```bash
$BASE/scripts/send.sh 011-511 "evaluate — {TASK_ID} cycle {N}"
```
Attendre `FROM:011-511|SCORE {N}` (timeout 10 min).

### Step 4 : Coach (011-811) — si score < 98
```bash
$BASE/scripts/send.sh 011-811 "coach — {TASK_ID} cycle {N} score {SCORE}"
```
Retour à Step 1 avec cycle N+1.

## Phase C — Finalisation (score ≥ 98)

```bash
mv plan-DOING/{CAT}/{task}.md plan-DONE/{CAT}/{task}.md
$BASE/scripts/send.sh 100 "FROM:011-111|DONE {TASK_ID} score:{SCORE} cycles:{N}"
```
