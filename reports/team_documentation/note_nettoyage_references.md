# Note de nettoyage des références et des identités Git

Document d'accompagnement du rapport final. Il consigne ce qui a été
nettoyé, ce qui ne peut pas l'être sans opération destructive, et ce qui
reste à décider.

Date : 22 août 2026.

---

## 1. Références nettoyées dans les fichiers du dépôt

Toutes les occurrences trouvées dans les fichiers versionnés étaient des
**noms de branche**, jamais des mentions d'auteur ou de contributeur. Elles
ont été reformulées de façon neutre, sans falsifier les faits.

| Fichier | Avant | Après |
|---|---|---|
| `README.md` | nom de branche d'audit | « branche d'audit independant » |
| `SUPERSEDED_RESULTS.md` | nom de branche d'audit | « branche d'audit dédiée, 2026-08-18 » |
| `models/FINAL_STATUS.json` | `provenance.branch` | `audit-independant-2026-08-18` |
| `src/pipelines/final_status.py` | même champ, à la source | idem |
| `models/advanced/recommendation_ranking/invalidated/INVALIDATION.json` | `invalidated_by` | « audit independant 2026-08-18 » |
| `models/pricing/metadata.invalidated.json` | `invalidated_by` | idem |
| `reports/42_leakage_correction_report.md` | nom de branche | « branche d'audit independant dediee » |
| `reports/45_final_corrected_decision.md` | nom de branche | idem |
| `reports/advanced/lead_independent_audit.md` | titre et branche | idem |

**Vérification** : plus aucun fichier versionné ne contient de mention
d'outillage, à l'exception documentée ci-dessous.

## 2. Exception conservée volontairement

`.gitignore` contient la règle `.claude/`.

Cette ligne **empêche** de committer un répertoire de configuration locale.
La supprimer n'effacerait rien : elle exposerait au contraire le dépôt au
risque que ce répertoire soit committé par la suite. Elle relève des
« dépendances techniques nécessaires » et est donc conservée.

## 3. Modification d'un fichier sous garde-fou

`models/FINAL_STATUS.json` est protégé par un test d'immuabilité, parce
qu'il porte la décision de prévision validée. La correction du champ
`provenance.branch` a changé son empreinte SHA-256.

Traitement retenu, plutôt qu'un simple contournement du test :

- l'empreinte épinglée a été mise à jour, avec la mention explicite du motif
  et l'empreinte précédente conservée en commentaire ;
- le garde-fou a été **renforcé**, pas affaibli : il distingue désormais les
  artefacts de prévision, strictement immuables et interdits à tout commit,
  du fichier de statut, dont les valeurs de décision sont comparées une par
  une à celles du commit de référence.

**Vérifié** : les cinq valeurs de décision de prévision (statut, modèle
quotidien, modèle 30 jours, WAPE30 macro, biais) sont identiques à celles du
commit d'origine. Seule une chaîne de provenance a changé.

## 4. Identités dans l'historique Git

### Constat

```
git shortlog -sne --all
     65  younesda <youneshachami9@ggit config --global user.name Younes>
```

**Aucun nom d'outil d'assistance n'apparaît comme auteur ou committer.** Les
65 commits sont attribués à une seule personne.

### Défaut découvert : adresse de courriel corrompue

L'adresse enregistrée est `youneshachami9@ggit config --global user.name Younes`.
Une commande shell y a manifestement été collée par inadvertance lors de la
configuration. Les 65 commits portent cette adresse invalide, ce qui empêche
notamment l'attribution correcte sur la forge.

**Correction non destructive appliquée** : un fichier `.mailmap` normalise
l'affichage dans `git log`, `git shortlog` et `git blame`. Après
application :

```
     65  Younes Hachami <youneshachami9@gmail.com>
```

**Action recommandée pour les commits futurs**, à exécuter une fois :

```bash
git config user.email "votre.adresse@example.com"
```

L'adresse figurant dans le `.mailmap` doit être remplacée par l'adresse
réelle souhaitée.

## 5. Ce qui exigerait une réécriture de l'historique

Ces éléments **n'ont pas été modifiés** : leur correction est destructive et
requiert une décision explicite.

### 5.1 Messages de commit

**29 commits** contiennent un pied de message mentionnant l'outillage de
développement.

Point important : **`.mailmap` ne corrige pas ce cas.** Il ne réécrit que
l'identité d'auteur et de committer, jamais le corps d'un message. Vérifié :
après application du `.mailmap`, les 29 commits conservent la mention.

Répartition par branche :

| Branche | Commits concernés |
|---|---:|
| `v4/pricing-recommendation-training` | 18 |
| `backup/claude-independent-improvements-pre-squash` | 13 |
| `lead/claude-independent-improvements` | 13 |
| `experiment/advanced-model-optimization` | 10 |
| `experiment/pricing-advanced-optimization` | 10 |
| `experiment/pricing-campaign-level` | 10 |
| `experiment/recommendation-advanced-ranking` | 10 |
| `experiment/wape15-stretch-goal` | 10 |
| `rebuild/final-enriched-dataset` | 10 |
| `product/v2-web-interface` | 5 |
| `feature/dockerized-model-api` | 3 |
| `lead/claude-independent-improvements-clean` | 3 |

Les branches partagent des commits communs : le total de lignes dépasse donc
29.

### 5.2 Noms de branche

Trois branches portent la mention dans leur nom :

| Branche | Emplacement |
|---|---|
| `lead/claude-independent-improvements` | locale |
| `backup/claude-independent-improvements-pre-squash` | locale, jamais poussée |
| `lead/claude-independent-improvements-clean` | **distante** |

Les deux premières sont locales : elles peuvent être renommées ou supprimées
sans effet sur la forge. La troisième est publiée ; la renommer implique de
créer la nouvelle référence puis de supprimer l'ancienne côté distant.

### 5.3 Options possibles, par ordre de risque croissant

1. **Ne rien faire.** Les mentions ne concernent que des messages de commit
   et des noms de branche d'archive. Aucun fichier livré n'en contient.
2. **Renommer ou supprimer les branches locales** — sans risque, aucun effet
   sur l'historique des commits.
3. **Renommer la branche distante** — nécessite une coordination si
   quelqu'un l'a déjà récupérée.
4. **Réécrire les messages des 29 commits** — opération destructive :
   tous les identifiants de commit changent, un `push --force` devient
   nécessaire, et toute copie locale existante diverge. **À n'engager
   qu'après confirmation explicite.**

Aucune de ces options n'a été engagée.

## 6. État final vérifié

- Aucun secret dans les fichiers versionnés.
- Aucun chemin local dans la documentation livrée.
- Fichiers documentaires en UTF-8, sans caractère altéré.
- Artefacts de prévision inchangés, garde-fou vert.
- Manifestes SHA-256 valides.
