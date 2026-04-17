# 161-961 Methodology — Structure et Categories

## Regles globales
- Maximum 10 tool calls par tache
- Ne JAMAIS renommer/deplacer des dossiers existants sans confirmation du Master
- Toujours verifier la memory avant de creer une categorie (anti-doublon)
- Mettre a jour memory.md apres chaque action

---

## BOOTSTRAP d'un nouveau service

### Etape 1 : Analyser les sources disponibles
```bash
ls ~/docs/{service}/plan/ 2>/dev/null       # sources vendor
ls ~/docs/{service}/ 2>/dev/null            # structure existante
```

### Etape 2 : Definir les categories

Regles de choix des lettres :
1. A = toujours le core fonctionnel principal du service
2. B = organisation, recherche, structure secondaire
3. C = notifications, contacts, communication sortante
4. D = temps reel, securite des donnees, chiffrement
5. E-F = features avancees propres au service
6. G-I = apps tierces, integrations, administration
7. J-L = API publique, deployment, infrastructure
8. M-N = federation, plans/pricing
9. O-P = business, clients
10. Q-R = support, blog
11. S-V = legal, releases, features marketing
12. W-Z = resources, company, non-categorise

Pour les services techniques (visio, desktop) : adapter librement, la convention A-Z est indicative.

### Etape 3 : Creer la structure
```bash
mkdir -p ~/docs/{service}/plan-TODO
mkdir -p ~/docs/{service}/plan-DOING
mkdir -p ~/docs/{service}/plan-DONE

# Pour chaque categorie :
mkdir -p ~/docs/{service}/plan-TODO/{LETTRE}-{nom}
```

### Etape 4 : Mettre a jour memory.md
Ajouter la ligne dans le tableau "Services documentes".

---

## AUDIT d'un service existant

### Etape 1 : Lister les anomalies

Chercher les patterns invalides :
```bash
# Prefixes numeriques (sauf services desktop qui utilisent ce pattern intentionnellement)
ls ~/docs/{service}/plan-TODO/ | grep '^[0-9]'
ls ~/docs/{service}/plan-DONE/ | grep '^[0-9]'

# Underscores
ls ~/docs/{service}/plan-TODO/ | grep '_'
ls ~/docs/{service}/plan-DONE/ | grep '_'

# Categories identiques en TODO et DONE (doublon de structure)
comm -12 <(ls ~/docs/{service}/plan-TODO/ | sort) <(ls ~/docs/{service}/plan-DONE/ | sort)
```

### Etape 2 : Detecter les doublons semantiques
Comparer avec le mapping cross-service en memory.md.
Exemples de doublons a signaler :
- Deux categories avec "business" dans le nom
- Une categorie qui couvre le meme perimetre qu'une autre lettre

### Etape 3 : Produire le rapport

Format du rapport dans le message de completion :
```
AUDIT {service} :
- {N} anomalies de nommage : {liste}
- {N} doublons detectes : {liste}
- {N} categories manquantes suggerees : {liste}
- Action requise : {oui/non}
```

---

## ADD CATEGORY

### Validation avant creation
1. Verifier que la lettre n'est pas prise dans ce service :
   ```bash
   ls ~/docs/{service}/plan-TODO/ | grep "^{LETTRE}-"
   ls ~/docs/{service}/plan-DONE/ | grep "^{LETTRE}-"
   ```
2. Verifier qu'il n'existe pas de categorie semantiquement equivalente (voir mapping memory.md)
3. Si la lettre est prise : proposer la lettre libre suivante

### Creation
```bash
mkdir -p ~/docs/{service}/plan-TODO/{LETTRE}-{nom}
```

---

## SYNC (audit de tous les services)

Executer AUDIT sur chaque service liste en memory.md.
Produire un rapport consolide avec :
- Nombre total d'anomalies par service
- Categories non couvertes par aucun service (gaps)
- Categories redondantes cross-service

---

## Decision : creer ou consolider ?

| Situation | Action |
|-----------|--------|
| Feature similaire dans un autre service | Creer quand meme — chaque service est independant |
| Doublon EXACT dans le meme service (plan-TODO + plan-DONE) | Signaler au Master, ne pas toucher |
| Categorie brute crawlee (prefixe 0-) | Signaler — a regrouper sous une lettre existante |
| Service sans aucune structure | BOOTSTRAP immediat |

---

## Anti-patterns a ne jamais reproduire

- `G-apps-0-{app-id}-{app-name}` : trop granulaire, utiliser `G-apps/0-{type}/{a-nom-app}/`
- `0-manage-*` en racine plan-TODO : dossiers crawles bruts non categorises
- Lettre manquante sans raison (ex: mail sans B) : verifier si intentionnel ou oubli
- Majuscules dans le nom de la categorie apres la lettre-cle
