# Conventions

## Numérotation

### Infra partagée (centaines, 1 seul agent)
| ID | Rôle |
|----|------|
| 900 | Architect global — point d'entrée humain |
| 800 | Coach global — methodology des agents infra |
| 600 | Indexer — données → vecteurs cherchables |
| 500 | Observer — observe les 3XX, produit bilans |
| 200 | Data Prep — données brutes → markdown propre |

### Triangle Architect (1 par chaîne 3XX)
| ID | Rôle |
|----|------|
| 945 | Écrit les system.md de 341-345, 741-745, 841-845 |
| 946 | Écrit les system.md de 346-34X, 746-74X, 846-84X |

### Agents dédiés (1 par maillon 3XX)
| Pattern | Rôle |
|---------|------|
| 3XX | Developer — exécute le process |
| 7XX | Curator — cure memory.md de 3XX |
| 8XX | Coach — améliore methodology.md de 3XX |

### Correspondance
Le suffixe lie les agents entre eux :
- 345, 745, 845, 945 forment un triangle
- 341, 741, 841 forment un triangle
- Le 9XX est toujours le même pour toute la chaîne

## Structure fichiers

```
prompts/
├── AGENT.md                    # Prompt de base universel (1 seul)
├── {ID}/
│   ├── agent.md → ../AGENT.md  # Symlink vers le prompt de base
│   ├── system.md               # Contrat (immutable)
│   ├── memory.md               # Contexte (curé)
│   └── methodology.md          # Méthodes (amélioré)
```

## Règle universelle

Tout agent lit 3 fichiers, exécute, point. Pas d'exception.

## Symlinks

```bash
# Créer les symlinks pour tous les agents
for dir in prompts/*/; do
  ln -sf ../AGENT.md "$dir/agent.md"
done
```

## IN/OUT

Chaque system.md définit explicitement :
- **INPUT** : ce que l'agent reçoit (type, format, source)
- **OUTPUT** : ce que l'agent produit (type, format, destination)
- **CRITÈRES DE SUCCÈS** : comment savoir que c'est réussi

Un agent ne fait JAMAIS quelque chose qui n'est pas dans son OUTPUT.
Un agent ne lit JAMAIS quelque chose qui n'est pas dans son INPUT.
