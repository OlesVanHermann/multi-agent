# Multi-Agent CLI Reference

Documentation complète de `infrastructure/multi-agent.sh`.

## Installation

```bash
cd multi-agent/infrastructure
chmod +x multi-agent.sh
```

---

## Infrastructure

### Démarrer

```bash
# Mode standalone (Redis seul)
./multi-agent.sh start standalone

# Mode complet (Redis + Dashboard + Bridge)
./multi-agent.sh start full
```

### Arrêter

```bash
./multi-agent.sh stop
```

### État

```bash
./multi-agent.sh status
```

Affiche :
- Conteneurs Docker en cours
- Agents connectés
- Projet actif

---

## Communication avec les agents

### RW (Read-Write) - Interactif

```bash
# Session interactive
./multi-agent.sh RW 100

# Envoyer un message unique
./multi-agent.sh RW 100 "go"
./multi-agent.sh RW 300 "PR-SPEC-300-ApiRange_Copy"
```

En mode interactif :
- Voir les réponses en temps réel
- Taper des commandes
- `exit` pour quitter

### RO (Read-Only) - Observer

```bash
# Observer un agent
./multi-agent.sh RO 100

# Observer plusieurs agents (pattern)
./multi-agent.sh RO '3*'      # 300, 301, 302, 303
./multi-agent.sh RO '*'       # Tous
```

---

## Gestion des agents

### Lancer un agent

```bash
# Master
./multi-agent.sh agent --role master

# Agent dev avec ID
./multi-agent.sh agent --role slave --id 300

# Avec projet spécifique
./multi-agent.sh agent --role slave --id 300 --project mon-projet
```

### Lister les agents

```bash
./multi-agent.sh list
```

### Supprimer un agent

```bash
./multi-agent.sh kill 300
```

Note : Supprime l'agent de Redis, mais le processus peut encore tourner (Ctrl+C).

### Effacer la conversation

```bash
./multi-agent.sh clear 300
```

### Voir les logs

```bash
# Derniers 50 messages (défaut)
./multi-agent.sh logs 300

# Derniers 100 messages
./multi-agent.sh logs 300 100
```

---

## Projets

### Créer un projet

```bash
./multi-agent.sh new-project mon-projet
```

Crée :
```
projects/mon-projet/
├── knowledge/
│   └── context.md
├── outputs/
└── exports/
```

### Activer un projet

```bash
./multi-agent.sh activate mon-projet
```

### Lister les projets

```bash
./multi-agent.sh projects
```

---

## Tâches

### Créer une tâche

```bash
./multi-agent.sh task "Analyser le code dans /src"
```

Retourne un `task_id` (ex: `task-1706345678-1234`).

### Voir le résultat

```bash
./multi-agent.sh result task-1706345678-1234
```

---

## Statistiques

### Stats globales

```bash
./multi-agent.sh stats
```

Affiche :
- Nombre d'agents
- Tâches en queue
- Résultats stockés
- Tâches par agent

### Exporter les résultats

```bash
# Projet actif
./multi-agent.sh export

# Projet spécifique
./multi-agent.sh export mon-projet
```

Génère un fichier JSON dans `projects/{projet}/exports/`.

---

## Aide

```bash
./multi-agent.sh help
```

---

## Exemples d'utilisation

### Workflow typique

```bash
# 1. Démarrer l'infrastructure
./multi-agent.sh start standalone

# 2. Terminal 1 : Lancer le Master
./multi-agent.sh agent --role master

# 3. Terminal 2 : Lancer un Dev
./multi-agent.sh agent --role slave --id 300

# 4. Terminal 3 : Observer
./multi-agent.sh RO 300

# 5. Terminal 4 : Envoyer des commandes
./multi-agent.sh RW 100 "go"

# 6. Voir les stats
./multi-agent.sh stats

# 7. Arrêter
./multi-agent.sh stop
```

### Debug

```bash
# Voir ce que fait un agent
./multi-agent.sh logs 300 200

# Relancer un agent bloqué
./multi-agent.sh kill 300
./multi-agent.sh clear 300
./multi-agent.sh agent --role slave --id 300
```

---

## Clés Redis utilisées

| Clé | Description |
|-----|-------------|
| `ma:agents` | Hash des agents connectés |
| `ma:inject:{id}` | Queue d'injection pour agent |
| `ma:conversation:{id}` | Historique conversation |
| `ma:conversation:{id}:live` | Stream temps réel |
| `ma:tasks:{project}` | Queue de tâches |
| `ma:results:{task_id}` | Résultats des tâches |

---

## Variables d'environnement

Pour le mode `full` avec bridge multi-VM, créer `.env.mac` :

```bash
VM_HOST=192.168.1.100
VM_USER=ubuntu
VM_SSH_PORT=22
SSH_KEY_PATH=~/.ssh/id_rsa
```

---

*Multi-Agent CLI v2.0*
