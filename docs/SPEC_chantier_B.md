# Chantier B : sujets, fichiers et ancres dans l'écran plan

**Statut : spécification à valider. Aucun code avant le feu vert d'Aurelien sur ce document.**
Rédigée le 25/11/2026 à partir de nos échanges et des deux guides de prompting de MiniMax H3
(`VIDEO_PROMPT_WRITING_GUIDE_ref_en.md` et `VIDEO_PROMPT_WRITING_GUIDE_base_en.md`).

## 1. Le but

L'écran plan sert à écrire un prompt H3 sans connaître les termes et les formulations de MiniMax.
On déclare des choses, puis on les place où on veut, avec les @, l'autocomplétion et le glisser-déposer.

Aujourd'hui, la gestion des références est bancale :

- une « référence » mélange le fichier, ce qu'on veut voir et la façon dont le clip l'utilise ;
- on ne sait pas si une référence est une image ou un son ;
- il faut passer par l'écran prises pour lui donner ses fichiers, et l'écran plan reste vide tant qu'on ne l'a pas fait ;
- un sujet ne peut avoir qu'une image ;
- une image ne peut être ni une première ou une dernière frame, ni un décor ;
- il manque des termes de rétention ;
- on passe son temps entre les paramètres du plan, le plan et les prises.

## 2. Vocabulaire

| Terme | Sens |
|---|---|
| **Fichier** | Une image ou un son importé dans le projet (écran Ressources). Son type vient du fichier. |
| **Sujet** | Ce qu'on veut voir, déclaré dans le plan : @chanteur, @bar. Il a un type et zéro, une ou plusieurs images, plus une voix éventuelle. |
| **Rôle** | Ce qu'une image apporte à un sujet, en texte court : « visage », « tenue », « décor ». |
| **Rétention** | À quel point un clip doit respecter un sujet, choisie par clip. |
| **Ancre** | Une image qui fixe une frame du clip : début, fin, ou keyframe à un instant. Ce n'est pas un sujet. |

La « référence » disparaît, comme mot et comme objet.

## 3. Ce qui appartient à qui

| Quoi | Où | Figé quand |
|---|---|---|
| Fichiers | Projet (écran Ressources, comme aujourd'hui) | Jamais. On ne peut supprimer que ceux qui ne servent à rien (§ 7). |
| Sujets (type, description, images et rôles, voix) | Le plan : plan maître, puis portions et suites, comme le reste du plan | Comme le reste du plan : dans la portion d'une prise, une fois faite |
| Rétention, ancres, textes | Chaque clip du plan | Idem |

Les sujets se recopient par les mécanismes actuels : plan d'une brindille, « Utiliser ce plan… », duplication de branche, import d'un plan.

Conséquence : **la branche ne porte plus de références.** Elle garde la taille d'image,
`ref_image_size`, le segment vidéo, la LoRA et l'upscale. Changer l'image d'un sujet dans la suite d'une
brindille ne vaut que pour les clips suivants. Les prises déjà faites gardent la leur dans leur portion.

## 4. Le plan (version 7, sans rétrocompatibilité)

```json
{
  "files": {
    "chanteur_face": {"kind": "image", "file": "refs/images/chanteur_face.png"},
    "chanteur_voix": {"kind": "voice", "file": "refs/voices/chanteur.wav"},
    "bar":           {"kind": "image", "file": "refs/images/bar.png"}
  },
  "subjects": {
    "chanteur": {"kind": "person", "description": "homme d'une quarantaine d'années, barbe courte",
                 "pictures": [{"file": "chanteur_face", "role": "visage"}],
                 "voice": "chanteur_voix"},
    "bar":      {"kind": "place", "description": "bar enfumé des années 50",
                 "pictures": [{"file": "bar", "role": "décor"}]}
  },
  "clips": [{
    "name": "clip_003", "frames": 137, "continue": false,
    "anchors": {"first": "bar", "last": null, "keyframes": [{"at": 2.5, "file": "chanteur_face"}]},
    "subjects": [
      {"name": "chanteur", "keep": "identical", "voice_keep": "timbre", "note": "porte un chapeau"},
      {"name": "bar", "keep": "partial", "note": "seulement le comptoir"}
    ],
    "summary": "@chanteur entre dans @bar et s'accoude au comptoir.",
    "description": "[Shot 1] … [Shot 2] At 00:03.200 …",
    "soundscape": "…",
    "music": "…",
    "prompt_override": null
  }]
}
```

- **Types de sujet** : `person`, `place`, `object`, `outfit`, `style`, `action`, `pose`. On pourra en ajouter plus tard.
- **Rétention de l'image** (`keep`) : `identical`, `partial`, `attribute` et `loose`. H3 les nomme fully_preserved, partially_preserved, attribute_transfer et weak_reference.
- **Rétention de la voix** (`voice_keep`, mode free uniquement) : `exact`, `partial`, `timbre` et `loose`. H3 les nomme fully_copy, partially_copy, reference et weak_reference.
- **`note`** : précise le sujet pour ce clip seulement. Elle s'ajoute à sa définition et justifie la rétention.
- **Liste des sujets du clip** : elle se déduit des @ écrits dans les textes. On ne l'édite pas à part. La liste `subjects` du clip ne porte que les réglages de chaque sujet.
- **Ce qui disparaît du clip** :
  - le `prompt` brut comme source principale (il ne reste que l'édition manuelle facultative du § 5.1) ;
  - les `{picture:NOM}` et `{voice:NOM}` ;
  - les blocs subject_definitions et retention_analysis écrits à la main ;
  - la liste `refs`.
- **Le nom d'un fichier dans `files`** se crée tout seul à partir du nom du fichier.
  - Le plugin seul s'en sert pour faire correspondre les nœuds « H3 Plan - Reference » et « H3 Plan - Voice ».
  - Encore se sert du chemin `file`.

## 5. Le prompt H3 composé

Encore et le plugin composent le prompt avec le même code (`plan_core` et `core`), à partir du plan.

1. **Numérotation par clip.** Seuls les sujets et fichiers de ce clip comptent.
   - Sujets : dans l'ordre de leur premier @.
   - Images : d'abord celles des sujets, puis les ancres qui ne sont pas déjà numérotées.
   - Audio : le son de la vidéo éditée en `<Audio 1>` s'il y en a un, puis les voix.
2. **summary** : un préfixe de tâche est ajouté automatiquement.
   - Ancre de début ou de fin : keyframe completion.
   - Vidéo éditée : video editing.
   - Clip qui continue (↪) : video continuation.
   - Sinon, s'il y a des images : reference generation.
   - Plusieurs tâches se cumulent, selon le guide.
3. **subject_definitions** : une ligne par sujet. Exemple : `<Subject 1> is a person: homme d'une quarantaine…, porte un chapeau; face from <Picture 1>, outfit from <Picture 3>.` Puis la ligne de voix officielle : `<Audio 2> is the voice-timbre reference for <Subject 1> (S1).`
4. **Libellé des images** : une image n'a son propre libellé qu'en ancre, comme le veut le guide. Exemples : `the shot begins from <Picture 4>`, `ends on <Picture 5>`, `at 00:02.500 the frame matches <Picture 2>`. Ces formules sont insérées dans `[Shot 1]` et dans le plan concerné.
5. **retention_analysis** : une ligne par sujet, avec le marqueur H3 et la note, sans `(Sx)`. Une ligne par voix.
6. **@nom** : chaque @nom des textes devient `<Subject N>` (S N).
7. **Limites par clip** : 9 images, 3 voix, 12 fichiers. Au-delà, c'est une erreur.
   - Une ancre de début sur un clip ↪ est une erreur, car sa première frame est déjà celle du clip précédent.
   - Une voix ou une rétention de voix en mode music_video est ignorée, avec un avertissement (comme aujourd'hui).

### 5.1 Modifier le prompt à la main

Le bouton **« Prompt H3 »** montre le prompt composé. On peut l'éditer directement.

- Dès la première modification, le clip garde ce texte dans `prompt_override`, et c'est lui qui part vers H3.
  Les champs structurés (résumé, plans, sujets, rétentions, ancres) sont conservés, mais ne pilotent plus le texte.
- Dans ce texte, on peut écrire les @nom, qui deviennent `<Subject N>` comme ailleurs.
  On peut aussi écrire `<Picture N>`, `<Audio N>` et `<Subject N>` directement.
  Une légende à côté de l'éditeur rappelle quelle image, quelle voix et quel sujet portent quel numéro dans ce clip.
- Les fichiers envoyés à ComfyUI restent ceux de la numérotation composée : les sujets du clip et ses ancres.
  Pour en changer, on change les sujets ou les ancres, et la légende suit.
- Un bandeau « Prompt modifié à la main » s'affiche sur le clip. Il propose « Revenir au prompt composé »,
  qui efface `prompt_override`.
- Si on modifie un champ structuré alors que le prompt a été modifié à la main, un avertissement le signale :
  « ce changement n'est pas dans le prompt modifié à la main ». On peut alors revenir au prompt composé ou garder son texte.
- Les vérifications restent actives sur le texte édité : limites par clip, numéros sans fichier, @ inconnu.

## 6. L'écran plan

```
┌ Bibliothèque ──────────┐┌ Clip 3  00:12.4 → 00:18.0 ──────────────────────┐
│ Fichiers  [+ importer] ││ Ancres : [début: 🖼bar] [fin: ░░] [+ keyframe]    │
│  🖼 🖼 🖼 🖼  🔊        ││                                                  │
│                        ││ Résumé   @chanteur entre dans @bar …             │
│ Sujets     [+ sujet]   ││ Plans    [Shot 1] …                              │
│  👤 @chanteur          ││ Son      …                                       │
│     🖼 visage 🖼 tenue  ││ Musique  …                                       │
│     🔊 voix            ││                                                  │
│  🏠 @bar   🖼 décor     ││ Sujets du clip (d'après les @) :                 │
│  🎸 @guitare 🖼 objet   ││  @chanteur [identique ▾] voix [timbre ▾] note … │
└────────────────────────┘│  @bar      [partiel ▾]  note …                  │
                          │ 4/9 🖼 · 1/3 🔊 · 5/12        [Prompt H3]       │
                          └──────────────────────────────────────────────────┘
```

- **La Bibliothèque** est un panneau de l'écran plan, aussi bien pour le plan maître que pour le plan d'une sélection.
  - **Fichiers** : les images et les sons du projet, avec leur vignette ou leur forme d'onde. On en importe depuis le panneau, par le bouton ou en déposant un fichier.
  - **Sujets** : on crée un sujet avec son type, son nom et sa description. On y glisse des images, chacune avec son rôle, et une voix. Une même image peut servir à plusieurs sujets.
  - Dans une portion figée, les sujets sont en lecture seule (grisés, avec une info-bulle).
- **Les @** :
  - L'autocomplétion propose les sujets du plan.
  - On peut glisser un sujet de la Bibliothèque dans un texte.
  - Un @ inconnu propose « créer le sujet @… ».
- **Les ancres** : on y glisse une image, depuis Fichiers ou depuis un sujet. Sur un clip ↪, l'ancre de début est grisée avec une info-bulle.
- **Les rétentions** se choisissent en mots simples ; les termes H3 ne s'affichent qu'en info-bulle.
- **Les images affichées** viennent de la Bibliothèque. Elles ne dépendent plus de la brindille sélectionnée et ne sont plus vides.

**Ce qui disparaît de l'interface** :

- l'onglet références des réglages de branche ;
- l'édition des références dans l'écran prises ;
- la liste « Références du clip » ;
- le bloc subject_definitions éditable.

## 7. L'écran Ressources

- Chaque fichier montre son usage :
  - **utilisé** : dans un plan maître, une suite, ou comme vidéo ou chanson du projet ;
  - **seulement par des prises** ;
  - **inutilisé**.
- Le bouton **« Supprimer les inutilisés »** efface d'un coup les fichiers inutilisés, après une confirmation qui les liste.
- La suppression d'un fichier « seulement par des prises » marche comme aujourd'hui : un avertissement, puis la suppression.

## 8. Le plugin ComfyUI-H3-ClipPlan

- PLAN_SPEC et plan.schema.json passent en version 7, et le composeur du § 5 entre dans `core.py`.
- Les nœuds Reference et Voice font correspondre les noms de `files`.
- LLM_SYSTEM_PROMPT est réécrit pour le nouveau format.
- La skill « h3-clip-plan » est mise à jour en proposant ses modifications.
- Les exemples sont convertis.
- Aucune rétrocompatibilité.

## 9. Hors du chantier

- Les vidéos de référence (reprendre la caméra, la découpe ou le rythme d'une vidéo).
- Le mode sans référence (FL2VA) et le nœud de keyframes intermédiaires (§ 11, question 2).
- L'enrichissement des types de sujet.

## 10. Découpage proposé

- **B1** : plan v7, composeur, validation, moteur (fichiers envoyés à ComfyUI d'après le plan et non plus d'après la branche), plugin et tests.
- **B2** : écran plan (Bibliothèque, ancres, sujets du clip, prompt H3).
- **B3** : écran Ressources (usage, « Supprimer les inutilisés »), retrait des anciens écrans, docs, README et captures.

Le déblocage de ▶▶ pendant une génération est indépendant. Il peut sortir avant, en 0.45.2.

## 11. Questions tranchées le 25/11

1. Oui. Les noms de `files` se créent automatiquement à partir du nom du fichier. Le plugin seul s'en sert pour relier ses nœuds.
2. Oui. Les ancres ne passent d'abord que par le mode avec références : les formules « the shot begins from `<Picture N>` » de la tâche keyframe completion. Le vrai mode FL2VA et ton nœud de keyframes intermédiaires viendront dans un chantier suivant.
3. Oui. La `note` par sujet et par clip : elle sert à la fois de précision dans la définition et de justification de la rétention.
4. Le prompt doit rester modifiable à la main : voir § 5.1.

## 12. Lot B1 : ce qui a été fait (25/11)

Plan v7, composeur, validation, moteur et plugin. Choix faits en cours de route, à valider avec B2 :

- **Réplique** : `@nom (S)` devient `<Subject N> (SN)`, la marque du locuteur d'une réplique (`<d>…</d>`).
  On n'a pas à connaître les numéros. *Revu en B2 (§ 13) : le locuteur est trouvé tout seul.*
- **Phrases d'ouverture** : la phrase de continuation (clip ↪) et celle de l'amorce cachée (nouvelle scène
  après le clip 1) sont ajoutées par le composeur au début de `[Shot 1]`. On ne les écrit plus.
- **Instruction d'édition** : elle ouvre le résumé de chaque clip qui édite la vidéo, après « The target video
  is an edited version of <Video 1>. ». Le marqueur `{edit}` disparaît.
- **Clips déjà générés** : leur entrée garde un `defs` (sujets, fichiers et instruction d'édition avec
  lesquels ils ont été faits). Le plan d'une brindille prend ses sujets en tête dans la suite ; les clips figés
  gardent les leurs. Changer l'image d'un sujet dans une suite ne touche donc que les clips suivants.
- **Son de la vidéo éditée** : `sound: original` donne `<Audio 1>: fully_copy`, `sound: h3` donne
  `<Audio 1>: reference`. Les lignes sur ce son ne restent que si la vidéo a un son (le plugin le sait au
  moment de générer).
- **Prompt écrit à la main** : ses sujets sont ceux qu'il nomme avec @ ; les numéros d'images et de voix sont
  ceux du clip (images de ses sujets, puis ancres).
- **Voix sans fichier** : elle n'est pas envoyée, ses lignes sont retirées et H3 choisit une voix (comme le
  plugin sans nœud de voix). Une image sans fichier est une erreur.
- **Pour B2** : `POST /api/projects/<nom>/plan/compose` renvoie, pour un plan en cours d'édition, le prompt
  H3 de chaque clip, sa légende (sujets, images, sons), ses tâches, ses erreurs et avertissements. L'écran plan
  n'aura pas à refaire le composeur en JavaScript ; `ui/plan_core.js` garde le calcul des temps.
- **▶▶** : il n'est plus refusé quand une génération de la branche attend ou tourne (la brindille passe par
  les générations en attente).
- Plugin 4.0 (plan v7) obligatoire. Pas de conversion des anciens plans (décidé le 25/11).
- Tests : `b1_api_test` (nouveau), `a1_api_test`, `a2_api_test`, `a3_api_test`, `v25_test`, `v40_test` et les
  tests unitaires passent ; les tests d'interface attendent B2.

## 13. Lot B2 et compléments : ce qui a été fait (25/11)

B2 et B3 sont livrés ensemble dans la **0.46** (pas de 0.45.2).

- **Écran plan** (`ui/plan_sections.js` réécrit) : onglets « Champs » et « Prompt H3 ». Champs : ancres
  (première image, images clés, dernière image ; la première est grisée sur un clip ↪), Résumé, Plans, Son,
  Musique, « Sujets du clip » (fidélité aux images, à la voix, note). Compteur images / voix / fichiers.
  Bibliothèque à droite : sujets du plan (fenêtre d'un sujet : genre, description, images avec leur rôle,
  voix), fichiers du projet (images, voix, import), glisser-déposer vers une ancre ou un sujet. Le prompt
  composé vient du serveur (`/plan/compose`, appel retardé après la frappe) ; le modifier à la main écrit
  `prompt_override`.
- **Locuteurs automatiques** (`mark_speakers`) : pour chaque `<d>…</d>`, `@nom (S)` explicite dans la phrase,
  sinon l'entrée du dialogue dont le texte correspond, sinon le premier sujet nommé dans la phrase, sinon le
  locuteur précédent de la même phrase. Numéros S1, S2… dans l'ordre de première prise de parole (Plans puis
  Résumé), comme le veut le guide MiniMax ; la ligne de la voix porte le même numéro.
- **Menu caméra « / »** : mouvements du guide MiniMax (puis amplitude et vitesse), coupe vers un nouveau plan,
  cadrages ; la phrase anglaise est insérée au curseur.
- **Ressources** : état de chaque fichier (utilisé, seulement des prises, inutilisé ; une génération en
  attente compte comme utilisation), « Supprimer les inutilisés ».
- **Suppression d'un projet** : définitive (décidé le 25/11), refusée si une génération ou un assemblage du
  projet attend ou tourne ; les copies côté ComfyUI sont retirées.
- Retirés : références de branche (fenêtres de branche, en-tête de bande), éditeur par sections, empreintes,
  `sha_test`, `roundtrip_test`.
- Tests : `b2_ui_test` (nouveau) ; les tests d'interface existants adaptés au plan v7.
