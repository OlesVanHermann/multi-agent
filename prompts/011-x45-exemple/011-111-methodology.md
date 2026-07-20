# 011-111 Methodology — Cycle x45

## Principe autonome
Le Master gère le cycle COMPLET sans demander confirmation.
JAMAIS "je continue ?" — FAIRE.

Après chaque dispatch unique, rendre immédiatement la main. Le bridge reprend
ce cycle à la réception de DONE/SCORE/BLOCKED. Aucun sleep, polling Redis/tmux,
contrôle de session, timeout de complétion, redispatch préventif, arrêt ou
redémarrage d'un autre agent.

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
Rendre la main ; reprise sur `FROM:011-711|DONE`.

### Step 2 : Dev (011-011)
```bash
$BASE/scripts/send.sh 011-011 "start — {TASK_ID} cycle {N}"
```
Rendre la main ; reprise sur `FROM:011-011|DONE`.

### Step 3 : Observer (011-511)
```bash
$BASE/scripts/send.sh 011-511 "evaluate — {TASK_ID} cycle {N}"
```
Rendre la main ; reprise sur `FROM:011-511|SCORE {N}`.

### Step 4 : Coach (011-811) — si score < 98
```bash
$BASE/scripts/send.sh 011-811 "coach — {TASK_ID} cycle {N} score {SCORE}"
```
Rendre la main ; reprise sur `FROM:011-811|DONE`.
Retour à Step 1 avec cycle N+1.

## Phase C — Finalisation (score ≥ 98)

```bash
mv plan-DOING/{CAT}/{task}.md plan-DONE/{CAT}/{task}.md
$BASE/scripts/send.sh 100 "FROM:011-111|DONE {TASK_ID} score:{SCORE} cycles:{N}"
```
