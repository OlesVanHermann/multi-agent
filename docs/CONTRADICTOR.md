# Contradictor 2XX — analyse et conclusion du 1XX

Chaque mono, x45 ou z21 possède un Contradictor local `NNN-2XX`. Sa cible est
toujours le `NNN-1XX` du même groupe. Il ne remplace ni l'Observer `5XX`, ni
l'Architect `9XX`.

## Valeur produite

Le `2XX` vérifie la cohérence de la chaîne :

```text
demande → compréhension du 1XX → décision → action → résultat
```

Il détecte notamment une mémoire ancienne utilisée comme whitelist, un refus
injustifié, une instruction déformée, un mauvais dispatch, une attente
impossible, une action annoncée mais non exécutée ou un résultat qui ne répond
pas à la demande.

## Deux actions

### `analyse`

`analyse` suffit : l'utilisateur ne fournit ni cible, ni paquet, ni méthode. Le
Contradictor déduit son `1XX`, retrouve l'activité pertinente et utilise les
preuves bornées disponibles. Une discussion peut suivre avec l'utilisateur.

La collecte technique correspond à :

```bash
./scripts/contradictor.sh collect 301
```

Le snapshot contient une `analysis_view` déjà corrélée : tâche active,
dispatchs du Master, doublons, terminaux, corrélations, conflits de mémoire et
artefacts ciblés. Le modèle lit cette vue avant les preuves brutes.

Chaque réponse se termine toujours par une section autonome :

```markdown
## Conclusion proposée pour NNN-1XX

Verdict : ÉTABLI | PROBABLE | NON CONCLUANT
Constat : ...
Preuve : ...
Origine : ...
Impact : ...
Correction demandée : ...
Résultat attendu : ...
```

La conclusion évolue pendant la discussion, mais reste à tout moment prête à
être envoyée. `analyse` n'envoie rien au `1XX`.

### `envoie`

`envoie` transmet uniquement la dernière conclusion au `1XX` cible. Le `2XX`
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

Le Contradictor peut lire les preuves autorisées concernant son `1XX` et écrire
son rapport sous `pool-requests/knowledge/contradictor/<ID-2XX>/`. Il ne lit
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

Le Contradictor utilise par défaut `gpt-5-6-sol`, `login3a` et l'effort `H`.
