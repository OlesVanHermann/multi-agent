# Contradictor 2XX — vue du triangle et relance par le 1XX

Chaque mono, x45 ou z21 possède un Contradictor local `NNN-2XX`. Il analyse
tous les agents locaux `NNN-YXX`, mais sa conclusion est toujours envoyée
uniquement au `NNN-1XX` du même groupe. Il ne remplace ni l'Observer `5XX`, ni
l'Architect `9XX`.

## Valeur produite

Le `2XX` commence par reconstruire l'intention utilisateur, puis la chaîne
complète du triangle :

```text
prompt utilisateur → amendements → résultat attendu
→ décision du 1XX → dispatchs → actions NNN-YXX
→ preuves physiques → résultat réellement livré
```

### Ne pas confondre les deux sens de « prompt »

| Source | Nom canonique | Usage |
|---|---|---|
| message utilisateur reçu par le `1XX` | `USER_REQUEST` | définit le résultat attendu |
| `system.md`, `memory.md`, `methodology.md` | `AGENT_INSTRUCTION` | explique rôle, contexte et méthode |
| messages entre agents | `INTER_AGENT_MESSAGE` | montre décisions et déclarations |
| code, artefacts, commits, hashes, tests | `PHYSICAL_EVIDENCE` | prouve ou réfute la réalisation |

Une instruction d'agent ne remplace jamais la demande utilisateur. Un `DONE`,
un échange ou un fichier modifié ne prouve jamais seul que le développement
fonctionne et répond à la demande.

Il détecte notamment une mémoire ancienne utilisée comme whitelist, un refus
injustifié, une instruction déformée, un mauvais dispatch, une attente
impossible, une action annoncée mais non exécutée ou un résultat qui ne répond
pas à la demande.

## Deux actions

### `analyse`

`analyse` suffit : l'utilisateur ne fournit ni cible, ni paquet, ni méthode. Le
Contradictor déduit son triangle et son `1XX`, retrouve l'activité pertinente
de chaque agent `NNN-YXX` et utilise les preuves bornées disponibles. Une
discussion peut suivre avec l'utilisateur.

La collecte technique correspond à :

```bash
./scripts/contradictor.sh collect 301
```

Le snapshot v3 contient `analysis_view.user_requests` dans l'ordre,
`evidence.agent_prompt_files`, `inter_agent_exchanges`,
`activity_by_agent` et `physical_evidence`. Il expose aussi la tâche active,
les dispatchs, doublons, terminaux, corrélations, conflits de mémoire et
artefacts ciblés.

Chaque réponse se termine toujours par une section autonome :

```markdown
## Conclusion proposée pour NNN-1XX

Verdict : ÉTABLI | PROBABLE | NON CONCLUANT
Demande utilisateur initiale : ...
Corrections ou précisions ultérieures : ...
Résultat attendu : ...
Exécution du prompt : OUI | PARTIELLE | NON | INDÉTERMINÉE
Développement réalisé : OUI | PARTIEL | NON | INDÉTERMINÉ
Validation réalisée : OUI | PARTIELLE | NON
Résultat effectivement livré : OUI | PARTIEL | NON
Échanges déterminants : ...
Écart entre demande et résultat : ...
Cause de l'écart : ...
Preuves : ...
Plan de développement ou correction : 1. ... 2. ... 3. ...
Agents à mobiliser : ...
Ordre de relance : ...
Critères d'acceptation : ...
Résultat final attendu : ...
```

`INDÉTERMINÉ` est obligatoire lorsqu'une preuve nécessaire manque. Si tout est
déjà développé, le plan se limite aux vérifications ou à la livraison encore
nécessaires.

La conclusion évolue pendant la discussion, mais reste à tout moment prête à
être envoyée. `analyse` n'envoie rien au `1XX`.

### `envoie`

`envoie` transmet uniquement la dernière conclusion au `1XX` cible, jamais aux
autres agents du triangle. Le `2XX`
retire le dialogue et les questions adressées à l'utilisateur, conserve une
copie exacte et une preuve d'envoi, puis confirme l'envoi dans le TUI.

S'il n'existe aucune conclusion, `envoie` commence par une analyse. Le message
reste consultatif : aucun `DONE`, aucune tâche métier et aucune transition de
workflow ne sont produits.

La transmission technique correspond à :

```bash
./scripts/contradictor.sh send 301
```

## Autorité et preuves

Le Contradictor peut lire les preuves autorisées concernant les agents
`NNN-YXX` de son triangle et écrire son rapport sous
`pool-requests/knowledge/contradictor/<ID-2XX>/`. Il ne lit
jamais les secrets, credentials, oracles ou données held-out.

Le collecteur technique conserve actuellement sa route de compatibilité
`/api/echo` et peut créer des snapshots bornés. Ce nom interne ne change pas le
nom officiel du rôle : **Contradictor**.

## Création

```bash
python3 scripts/scaffold-observers.py 345 \
  --directory-name 345-mon-projet \
  --contradictor-suffix 245 \
  --contradictor-login login3a
```

Le Contradictor utilise par défaut `opus-5`, `login3a` et l'effort `M`.
