# HOW TO WRITE AND REWRITE PROMPTS

## Objet du changement v3.2.X

Les agents avaient tendance à concentrer leur raisonnement et leurs réponses
sur les règles, enveloppes, dispatchs et checklists au lieu de la finalité de
leur rôle. À partir de cette migration, un prompt doit pondérer la mission ainsi :

```text
70 % résultat métier
20 % vérification et qualité
10 % processus et traçabilité
```

Les frontières fortes de sécurité restent absolues. La pondération concerne
l'attention, la rédaction et le critère de réussite ; elle ne permet jamais de
contourner une protection.

## Règle normative

Un agent n'a pas réussi parce qu'il a suivi son workflow. Il a réussi lorsque le
résultat attendu existe, fonctionne, répond à l'intention et possède les preuves
proportionnées au risque.

Les règles mécaniques sont appliquées silencieusement. Elles ne sont racontées
que lorsqu'elles :

- bloquent réellement le résultat ;
- modifient la qualité ou la portée du résultat ;
- nécessitent une décision de l'utilisateur ;
- constituent une preuve directement utile.

Une réponse normale présente, dans cet ordre :

1. résultat obtenu ;
2. preuves utiles ;
3. limites ou décisions restantes.

## Comment écrire un nouveau prompt

Le `system.md` commence par :

```markdown
# Agent — rôle

## Priorité au résultat

Finalité : <valeur produite>.

Réussite observable :
- <livrable ou comportement attendu> ;
- <test ou preuve> ;
- <absence de régression importante>.

Le processus est un moyen appliqué silencieusement.
```

Le reste du triplet est réparti ainsi :

| Fichier | Contenu |
|---|---|
| `system.md` | finalité, résultat, entrées/sorties, frontières fortes |
| `memory.md` | faits et contexte courant, jamais une whitelist |
| `methodology.md` | méthode adaptable et vérifications utiles |
| scripts | transport, corrélation, validation et mécanique déterministe |

Une même règle ne doit pas être répétée dans toutes les couches. La répétition
donne artificiellement plus de poids au processus qu'au travail.

## Finalité attendue par rôle

| Rôle | Finalité principale |
|---|---|
| Principal mono | accomplir sa mission fonctionnelle et livrer le résultat |
| Master `1XX` | faire aboutir la demande jusqu'à un résultat livré et vérifié |
| Contradictor `2XX` | améliorer la décision du Master par une conclusion actionnable |
| Developer `3XX` | produire un livrable fonctionnel, intégré et vérifié |
| Observer `5XX` | établir si le résultat satisfait réellement le besoin |
| Curator `7XX` | donner le contexte minimal permettant au Developer de réussir |
| Coach `8XX` | améliorer la probabilité de réussite du prochain cycle |
| Architect `9XX` | maintenir une structure qui facilite la production |

## Obligations des créateurs 150, 160 et 170

Les trois créateurs doivent écrire le contrat résultat-first dans chaque nouvel
agent, indépendamment du projet :

- `150` : principal mono et Contradictor ;
- `160` : sept rôles x45 ;
- `170` : sept rôles z21 et leurs contextes interchangeables.

Ils doivent définir la valeur métier et les critères observables avant les
détails de communication. Ils ne doivent jamais générer un agent dont le succès
est seulement « dispatch effectué », « fichier écrit » ou « workflow suivi ».

Ils doivent également générer le contrat de fin de cycle canonique : verdict
Observer parmi `BLOCK_DEV|READY_FOR_INTEGRATION|BLOCK_INTEGRATION|ACCEPT_WITH_IMPROVEMENTS`,
séparation des défauts Dev/actions Phase C/améliorations facultatives, Phase C
appartenant au Master et Coach non bloquant. Aucun template ne doit encoder
`score < 98` comme motif suffisant de nouveau cycle.

Les sources normatives sont :

- `prompts/AGENT.md` et `prompts/RULES.md` ;
- `prompts/150-create-mono/150-150-system.md` ;
- `prompts/160-create-x45/160-160-system.md` ;
- `prompts/170-create-z21/170-170-system.md` ;
- `templates/prompts/` et `templates/x45/prompts/`.

## Réécriture des agents déjà installés

Les répertoires d'agents sous `prompts/` sont des données projet et ne sont pas
synchronisés par `rsync`. La release fournit donc une migration sémantique
idempotente :

```bash
python3 patch/rebalance-agent-prompts.py --check
python3 patch/rebalance-agent-prompts.py
```

La migration :

- sélectionne uniquement les prompts exécutables ;
- ignore les memories, methodologies, documents, archives et symlinks loaders ;
- déduit la finalité depuis le rôle ;
- ajoute `Priorité au résultat` sans remplacer le contenu métier local ;
- injecte le contrat spécialisé de livraison dans les rôles 1XX/3XX/5XX/7XX/8XX/9XX ;
- ajoute le contrat de génération aux créateurs 150/160/170 ;
- sauvegarde chaque original sous
  `removed/rebalance-prompts/<timestamp>/` ;
- affiche tous les fichiers modifiés et `updated=N` ;
- ne produit aucun changement lors d'une seconde exécution.

`--refresh` est réservé au développement de la release : il remet à jour un
bloc normatif déjà présent. L'upgrade public utilise l'ajout idempotent normal
et ne réécrit donc pas un bloc local déjà migré.

## Intégration automatique dans `upgrade.sh`

À partir de la release publique v3.2.X contenant cette migration :

```bash
./patch/upgrade.sh --dry-run
./patch/upgrade.sh
```

Le dry-run affiche le nombre de prompts à migrer. La passe réelle :

1. archive l'installation dans `removed/<timestamp>_upgrade_backup/` ;
2. met à jour le framework, les templates, les exemples et la documentation ;
3. synchronise `AGENT.md` et `RULES.md` comme prompts canoniques ;
4. exécute `rebalance-agent-prompts.py` sur les prompts projet préservés ;
5. écrit le rapport dans
   `removed/<timestamp>_upgrade_backup/prompt-result-migration.log` ;
6. conserve aussi les copies fichier par fichier sous
   `removed/rebalance-prompts/<timestamp>/`.

Opt-out d'urgence, non recommandé :

```bash
MA_SKIP_PROMPT_REBALANCE=1 ./patch/upgrade.sh
```

Cet opt-out conserve les anciens prompts projet, mais `AGENT.md`, `RULES.md` et
les nouveaux templates du framework sont tout de même mis à jour.

## Après l'upgrade

Contrôler :

```bash
python3 patch/rebalance-agent-prompts.py --check
rg -L '## Priorité au résultat' prompts/*/*-system.md
python3 -m pytest tests/test_prompt_result_priority.py -q
```

Le résultat attendu de `--check` est `updated=0`. Les agents déjà en session
doivent relire leur prompt ou être redémarrés lors de la fenêtre opératoire ; la
migration ne redémarre aucun service elle-même.

Pour approfondir un prompt très personnalisé, l'Architect peut ensuite préciser
manuellement ses critères observables. Il ne doit pas recopier les détails
mécaniques déjà garantis par les scripts.

## Restauration

Si un prompt local doit être restauré, utiliser sa copie sous :

```text
removed/rebalance-prompts/<timestamp>/<chemin-original>
```

Comparer avant restauration :

```bash
diff -u prompts/NNN-projet/NNN-XXX-system.md \
  removed/rebalance-prompts/<timestamp>/prompts/NNN-projet/NNN-XXX-system.md
```

La restauration est une décision opérateur ; `upgrade.sh` ne supprime jamais
les sauvegardes.

## Promotion mx9 vers la release publique

Le patch envoyé à mx9 doit contenir ensemble :

- les prompts canoniques et les créateurs 150/160/170 ;
- les templates et exemples migrés ;
- `patch/rebalance-agent-prompts.py` ;
- l'intégration dans `patch/upgrade.sh` ;
- ce document et les liens README ;
- les tests de migration et de couverture des prompts.

Sur mx9 : inspecter le diff, exécuter toute la suite de tests, générer le
manifest de checksums par le processus de release, publier un tag v3.2.X, puis
tester `upgrade.sh --dry-run` et `upgrade.sh` sur une copie représentative d'une
ancienne installation avant publication générale.

## Critères d'acceptation de la release

- les trois créateurs génèrent des prompts résultat-first ;
- tous les `system.md` livrés contiennent la priorité au résultat ;
- une ancienne installation conserve ses contenus métier locaux ;
- chaque prompt modifié possède une sauvegarde récupérable ;
- le second upgrade affiche zéro migration ;
- aucun service n'est démarré ou redémarré par la migration ;
- la suite de tests passe intégralement.
