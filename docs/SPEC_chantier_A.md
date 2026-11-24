# Chantier A : des prises qui portent leur propre portion de plan

**Statut : spécification à valider. Aucun code avant le feu vert d'Aurelien sur ce document.**
Rédigée le 23/11/2026 à partir de nos échanges. Elle remplace la section A de la passation 0.40.

## 1. Le but

« Pouvoir tester des changements de prompts et de paramètres de génération tout en conservant une
continuité. » Tout ce qui rend l'itération rébarbative est à éviter.

Aujourd'hui, le plan est unique par projet. Le modifier invalide les prises déjà faites (hachuré jaune),
et il faut des points de sauvegarde pour revenir en arrière. Demain, chaque prise garde ce avec quoi elle
a été faite, et rien ne s'invalide plus.

## 2. Vocabulaire

| Terme | Sens |
|---|---|
| **Branche** | Un jeu de réglages figés : taille, mode, vidéo, chanson, fichiers des références. Contient des prises. |
| **Prise** | Une génération d'un clip. Elle ne change plus une fois faite. |
| **Portion de plan** | Ce avec quoi une prise a été générée (détail au § 3.2). Figée, rangée dans la fiche de la prise. |
| **Prédécesseur** | La prise qui précède une prise dans le temps : celle qu'elle continue (↪), ou celle après laquelle elle a été minutée (✂). Toutes les prises en ont un, sauf celles du clip 1. |
| **Brindille, ou sélection** | Une chaîne de prises 1 → 2 → … → k, de la prise du clip 1 jusqu'à une prise k, la « feuille ». |
| **Suite** | Les clips pas encore générés après la feuille d'une brindille. Modifiable, propre à cette brindille. |
| **Plan d'une sélection** | Les portions des prises de la brindille (lecture seule), puis sa suite (modifiable). |
| **Plan maître** | La suite de la « sélection vide » d'une branche : le plan d'où part le clip 1. |

## 3. Le modèle

### 3.1 Ce qui est figé par branche

Ces réglages restent modifiables tant que la branche n'a aucune prise. Ils sont figés dès la première
génération :

- le mode (clip musical, libre) ;
- la taille de l'image ;
- la vidéo de départ ou éditée, avec son segment ;
- la chanson, et sa position par rapport à la vidéo de départ ;
- **les fichiers des références** (quelle image, quelle voix pour chaque nom).

**Ajouter un nom de référence reste permis** : on peut faire entrer un nouveau personnage au clip 6. Ce
qui est interdit, c'est de changer ou de retirer le fichier d'un nom déjà utilisé par une prise : pour
cela, on duplique la branche (§ 4.6).

### 3.2 La portion de plan d'une prise

Elle est enregistrée au lancement, telle qu'elle a servi, et ne change plus :

- le prompt, la longueur, le lien (✂ nouvelle scène ou ↪ continue) ;
- les noms de références utilisés par le clip ;
- la consigne commune `{edit}` telle qu'elle était au lancement (mode édition) ;
- la taille des images de référence ;
- la graine, le modèle, l'échantillonneur, les étapes, les LoRA, l'upscale et ses réglages.

### 3.3 Le plan d'une sélection

Pour une brindille 1 → 2 → 3a, le plan est composé ainsi :

1. les portions de 1, 2 et 3a, retrouvées en remontant les prédécesseurs depuis 3a ;
2. la suite de 3a : les clips 4, 5, 6… prévus, sans trou.

Les portions ne sont jamais recopiées : elles n'existent qu'une fois, dans la fiche de leur prise. Seule
la suite est une donnée propre à la brindille.

Modifier la suite de 3a ne touche que 3a. Le plan maître n'est pas modifié par le travail sur une
sélection, car une longueur changée dans une sélection pourrait décaler tout le reste.

### 3.4 L'héritage : toute génération copie le plan de la sélection d'où on la lance

On lance une prise du clip k depuis une brindille, dont le plan est P :

- **sa portion** est le clip k tel que réglé dans le panneau de lancement ;
- **sa suite** est une copie des clips k+1, k+2… de P.

Ensuite, les deux vivent indépendamment.

**Si plusieurs brindilles passent par la prise de départ, l'utilisateur choisit le plan.** Exemple :
nouvelle prise du clip 3 en partant de 3a, alors que 3a a deux suites générées, 4a et 4b. Le panneau de
lancement propose « Partir du plan de : 1 → 2 → 3a ▾ », avec les brindilles …→ 4a et …→ 4b, et les met
en surbrillance dans le graphe. Par défaut,
c'est la sélection en cours. Si l'on prend …→ 4a, le clip 4 de la nouvelle brindille est pré-rempli avec
la portion de 4a, qui redevient une simple valeur par défaut, modifiable.

### 3.5 Le minutage suit la chaîne réelle

- Le début d'un clip dépend des longueurs réelles des prises qui le précèdent dans la brindille. Si le
  clip 3 a été rallongé dans le panneau de lancement, le clip 4 commence après *cette* prise 3. En clip
  musical, c'est ce qui garde la chanson calée.
- **Une prise ✂ (nouvelle scène) se rattache à la brindille sélectionnée** (comme avant la refonte),
  si la prise k-1 de la sélection la fait commencer au même moment que celle après laquelle elle a été
  faite. Sinon, elle reste rattachée à celle-ci.
  - En clip musical et en édition, le moment compte, à cause de la chanson et de la vidéo source.
  - En mode libre, elle peut suivre n'importe quel prédécesseur.
  - Exemple : le clip 3 ✂ a été fait après 2a (5 s). Il est compatible avec 2b si 2b fait aussi 5 s,
    pas si elle fait 7 s.
- Une prise ↪ ne suit que la prise qu'elle continue.

### 3.6 Ce qui fige quoi, en résumé

| Élément | Modifiable ? |
|---|---|
| Portion d'une prise | Jamais |
| Suite d'une brindille | Toujours |
| Plan maître | Toujours |
| Réglages figés d'une branche (§ 3.1) | Tant que la branche n'a aucune prise |
| Noms de références | Ajout toujours possible ; changement de fichier seulement si aucune prise ne l'utilise |

## 4. Les actions

### 4.1 Nouvelle prise d'un clip (fork)

Sur une prise 3a, « Nouvelle prise » ouvre le panneau de lancement, pré-rempli avec la portion de 3a.

- **La graine est celle de 3a**, avec un bouton 🎲 pour en tirer une nouvelle. Si rien n'a changé par
  rapport à 3a, le panneau le signale (le résultat serait identique) et propose 🎲.
- La nouvelle prise 3c se place à côté de 3a, sous la même prise 2.
- Son plan suit le § 3.4, avec le choix de la brindille si plusieurs passent par 3a.

### 4.2 Clip suivant

Après une prise k, « Clip suivant » ouvre le panneau de lancement, pré-rempli avec le clip k+1 de la
suite de la sélection. **La graine est toujours tirée au hasard** ; elle est affichée dans la fenêtre et
reste modifiable.

### 4.3 ▶▶ Compléter

Génère les clips restants de la suite de la sélection, avec leurs valeurs, sans ouvrir de fenêtre. Comme
pour « Clip suivant », la graine de chaque clip est tirée au hasard.

### 4.4 Assembler

Assemble une brindille. Le plan envoyé au plugin, si c'est lui qui assemble, est composé à partir des
portions. La fiche ≡ de la vidéo contient le plan complet de la brindille.

### 4.5 Modifier un plan

- **Plan maître d'une branche** : tous les clips sont modifiables, on peut en ajouter et en supprimer, et
  la frise est calculée sur ses propres longueurs. C'est l'écran pour écrire un plan entier d'un coup.
- **Plan d'une sélection** : les clips générés sont en lecture seule ; la suite est modifiable et on peut y
  ajouter des clips. La frise suit les longueurs réelles de la brindille.

### 4.6 Créer une branche

- **Vide**, comme aujourd'hui.
- **Par duplication d'une branche** : ses réglages et son plan maître sont copiés, puis au choix :
  - **sans clips** : tout est modifiable jusqu'à la première génération ;
  - **avec les clips de la sélection en cours** : ils sont repris par référence, sans copie de fichier,
    et figés. On génère à partir du clip suivant. Le plan maître de la nouvelle branche est alors le plan
    de la sélection.
- On ne peut pas changer, dans la nouvelle branche, une référence utilisée par un clip repris. La fenêtre
  de duplication indique jusqu'où on peut reprendre, par exemple : « Marie apparaît au clip 8 : tu peux
  reprendre les clips 1 à 7 ».

### 4.7 Supprimer

- **Une prise dont d'autres dépendent ne se supprime qu'avec tout ce qui en dépend.** La confirmation le
  liste, par exemple : « Supprimer 3a supprime aussi 4a, 4b et les clips 1–3 repris dans la branche 3. »
- **Supprimer une branche** ne supprime pas les prises qu'une autre branche reprend.
- **Tout ce qui est supprimé va dans une corbeille.** On en restaure un élément d'un clic, avec ses
  dépendants, et on vide la corbeille à la main. Rien n'est effacé du disque avant.

### 4.8 Importer et exporter un plan JSON

- **Importer se fait à la création d'une branche** : son plan maître est le fichier importé.
- **On peut réimporter un plan dans une branche tant qu'elle n'a aucune génération** : il remplace son
  plan maître. Ensuite, l'import n'est plus possible dans cette branche ; on crée une branche.
- **Exporter** donne le plan d'une sélection, utilisable tel quel dans ComfyUI avec les nœuds du plugin.

## 5. Les écrans

- **L'écran Prises devient l'écran principal. L'onglet Plan disparaît.**
- **Panneau de lancement**, ancré à droite de l'écran Prises. Le graphe reste visible à gauche, recentré
  sur la prise de départ. Il contient :
  - pour un seul clip : prompt (avec l'éditeur de sections `@sujet`), longueur, lien ✂/↪, références,
    graine 🎲, réglages de génération ;
  - le passage de la chanson ou de la vidéo couvert par le clip ;
  - le choix de la brindille de départ quand il y en a plusieurs : survoler ou choisir une brindille la
    met en surbrillance dans le graphe, avec ses clips, et « plan entier » déplie son plan complet en
    lecture seule dans le panneau.
  - Pré-remplissage des réglages de génération : pour une nouvelle prise, ceux de la prise de départ ;
    pour un clip suivant, ceux de la branche, à défaut ceux du projet.
- **Écran de plan** (dédié, avec un bouton « ← Prises »), pour le plan maître ou le plan d'une sélection :
  - liste des clips, éditeur de clip, frise ;
  - annuler et rétablir (Ctrl+Z / Ctrl+Y) pendant l'édition ;
  - importer et exporter.
- **Fenêtre « Réglages de la branche »** (par-dessus) : mode, taille, vidéo, chanson, références, consigne
  `{edit}` par défaut, découpage sur les plans. Les réglages figés sont grisés, avec la raison.
- **Corbeille** (par-dessus) : prises et branches supprimées, restaurer, vider.

Une règle pour toutes les fenêtres : par-dessus l'écran Prises si le contenu est léger, écran dédié avec
« ← Prises » s'il est chargé.

### 5.1 Ce qui est conservé dans l'écran Prises

Les maquettes ne montrent que ce qui change. **Tout le reste du fonctionnement actuel est conservé**,
notamment :

- **Affichage** : vues Arbre (par défaut) et Colonnes ; ajuster, zoom (molette, Maj + molette), glisser
  pour se déplacer ; vue d'ensemble et sa position (coins) ; Actualiser ; « son au survol ».
- **Prises** : clic pour choisir (avec ses ascendants) ; lecture au survol ; aperçu agrandi au
  double-clic ; durée et graine affichées ; champ graine (une valeur + Entrée lance une prise avec cette
  graine) ; ▾ prise réglée (LoRA, upscale, graine) ; ≡ portion de plan.
- **Branches** : carte de branche (taille, chanson, références, upscale, LoRA) ; renommer (double-clic) ;
  replier et déplier ; ▶▶ compléter ; supprimer ; + nouvelle branche.
- **Colonnes de clips** : en-tête par clip ; colonne « Vidéo de départ ».
- **File** : générations en attente ou en cours dans le graphe, progression, annuler, ⏹ Arrêter, durée
  estimée, file en pause.
- **Volet des vidéos assemblées** : lecture, fiche ≡, « centrer la vue sur la dernière prise »,
  replier le volet.

Disparaissent seulement de cet écran : le hachuré et sa légende, « ⟲ refaire », l'avertissement des prises
invalidées à l'assemblage, « restaurer l'état de cette vidéo » (lié aux points de sauvegarde), et les
réglages propres à un clip (⚙ en tête de colonne : LoRA et upscale du clip pour toutes les branches).
Avant chaque livraison, les tests de bout en bout existants de ces fonctions restent au vert.

## 6. Technique

- **Fiche de prise immuable.** Elle contient la portion de plan, le prédécesseur et la branche d'origine.
- **Les suites et les plans maîtres sont rangés à part**, dans un fichier du projet indexé par prise et par
  branche. Les fiches de prise ne sont jamais réécrites.
- **Plan composé à l'envoi.** Encore compose, pour chaque génération et chaque assemblage, le plan complet
  qu'attend le plugin : les portions de la brindille, puis le clip à générer, puis la suite. Il l'envoie
  puis le jette.
- **Une génération en file garde le plan composé à son lancement** : modifier ensuite une suite ne la
  change pas.
- **Le plugin ne change pas.**
  - Encore désactive déjà la suppression automatique des prises « périmées » (`delete_stale: False`).
  - Encore n'envoie qu'une génération à la fois, donc le `plan.json` de la branche dans ComfyUI peut être
    remplacé à chaque envoi.
  - L'empreinte d'une prise, côté plugin, contient son heure de début. Pour une prise ✂ utilisée après un
    autre prédécesseur compatible, Encore corrige la fiche qu'il envoie, comme il le fait déjà pour
    l'assemblage de prises invalidées (`rewritten_record`).
- **Branche dupliquée avec ses clips** : elle référence les prises reprises de l'autre branche, sans
  recopier ni la fiche, ni le latent, ni l'aperçu.
- **Pas de découpage technique à part** (décidé le 23/11, après A1) : on découpe au fil des évolutions,
  quand une évolution crée un morceau nouveau (A1 : `plans.py`, `plan_launch.js` ; A2 : `plan_branch.js`).

## 7. Ce qui disparaît

- Le hachuré jaune et les états « invalide » d'une prise.
- L'assemblage de prises invalidées et son avertissement (`takeplan.invalid_chain` et la suite), et le
  bouton « Refaire ».
- **Les points de sauvegarde** : `checkpoints.py`, leur fenêtre, leur ménage automatique, les points
  automatiques avant import, avant restauration et à chaque assemblage, et leurs tests. Ils sont remplacés
  par la corbeille, l'import en nouvelle branche et Ctrl+Z.
- L'onglet Plan et le `plan.json` unique par projet.
- La case « reporter aussi dans le plan maître » et la marque ✎, prévues avant ces échanges.
- Les réglages propres à un clip (LoRA et upscale par clip, `clip_defaults` dans `project.json`) : les
  réglages se règlent par prise dans le panneau de lancement.
- La graine par clip dans le plan maître et dans les suites : elle n'existe plus que dans les portions des
  prises. Une graine présente dans un plan JSON importé est ignorée.
- **Aucune compatibilité ni migration** : les projets existants seront recréés en réimportant leur plan
  JSON.

## 8. Découpage proposé

Chaque lot est livré avec la suite de tests au vert. Les tests des fonctions supprimées sont retirés, et
de nouveaux tests couvrent chaque lot.

| Lot | Contenu |
|---|---|
| **A1. Fondations** | Fiches immuables avec portion et prédécesseur ; suites et plans maîtres ; plan composé à l'envoi ; minutage par chaîne ; fin du hachuré et de l'assemblage de prises invalidées ; panneau de lancement (nouvelle prise, clip suivant) ; écran de plan (maître et sélection) à la place de l'onglet Plan ; choix de la brindille de départ (4a / 4b) ; retrait des points de sauvegarde. **Livré en 0.42.** |
| **A2. Branches** | Réglages figés grisés avec leur raison ; fenêtre « Réglages de la branche » ; création d'une branche vide, depuis un fichier de plan ou par duplication (sans clips ou avec les clips de la sélection) ; prises ✂ compatibles ; « Importer un plan… » sur l'écran du plan maître seulement ; ↻ sur une génération en file ou en cours. Détail au § 10. |
| **A3. Suppression et corbeille** | Suppression en cascade avec confirmation ; protection des prises reprises par une autre branche ; corbeille ; Ctrl+Z dans l'écran de plan. |

L'ordre A1 → A2 → A3 est imposé par les dépendances. Après A1, l'appli est utilisable avec le nouveau
modèle ; seuls la duplication et la corbeille manquent.

## 9. Points à préciser pendant la réalisation

- **Comment l'écran Prises montre une prise ✂ utilisable après plusieurs prédécesseurs** (§ 3.5) : elle
  est rattachée au sien et proposée ailleurs comme compatible. La présentation exacte sera montrée avant
  d'être codée.
- **Le maquettage des nouveaux écrans** (panneau de lancement, écran de plan, réglages de la branche,
  corbeille) sera soumis avant d'être codé.

## 10. Lot A2 : précisions (maquettes `maquettes_A2.html`)

- **Créer une branche** : une fenêtre, trois choix.
  - *Vide* : réglages et plan maître de la dernière branche (comme en 0.42).
  - *À partir d'un fichier de plan* : son plan maître est le fichier ; réglages de la dernière branche.
  - *Dupliquer une branche* : sans clips (réglages + plan maître, tout modifiable jusqu'à la première
    génération) ou avec les clips 1 à k de la sélection (k choisi, au plus la longueur de la sélection).
    La fenêtre liste les références avec le premier clip qui les utilise : celles des clips repris sont
    gardées, les autres seront modifiables. Taille, mode, chanson et vidéo sont ceux de la branche source.
- **Clips repris** : la nouvelle branche enregistre la prise reprise la plus avancée (`project.json`) ; les
  prises ne sont ni copiées ni déplacées (elles sont rangées par clip, pas par branche). Dans l'écran des
  prises, elles apparaissent dans la bande de la nouvelle branche, estompées, en pointillés, marquées
  « ⇡ B1 » : on les lit et on les choisit, sans ↻ ni graine. Encore envoie leurs latents dans la copie de
  travail de la nouvelle branche côté ComfyUI, comme pour toute chaîne.
- **Fenêtre « Réglages de la branche »** (`ui/plan_branch.js`) : taille d'image, taille des références,
  mode, contexte, vidéo de départ ou éditée et son segment, chanson, fichiers des références, LoRA en plus,
  upscale. Elle remplace « références… », « LoRA… » et « Upscale… » de l'en-tête de branche. Ce qui est figé
  est grisé dès l'ouverture, avec une infobulle qui dit pourquoi et comment faire (dupliquer la branche) ;
  le refus côté serveur reste comme garde-fou. Même règle dans ⚙ Réglages du plan.
- **Prises ✂ rattachées à la sélection** (décidé le 23/11, remplace la carte « ✂ compatible » de la
  maquette 4) : une prise ✂ du clip k est dessinée une seule fois, sous la prise k-1 de la brindille
  sélectionnée si celle-ci la fait commencer au même moment que son prédécesseur d'origine (en mode libre :
  toujours), sinon sous son prédécesseur d'origine. Sa suite (prises faites après elle) la suit. La
  brindille se calcule en remontant les prédécesseurs, sauf aux coupes ✂ où elle suit la sélection. Plan
  de la sélection, ▶▶, assemblage et envoi suivent cette brindille ; la fiche envoyée au plugin est réécrite
  (`rewritten_record`).
- **Vidéo de départ ou éditée** (décidé le 23/11) : le fichier est un réglage du projet (« Réglages du
  projet »), modifiable tant qu'aucune branche n'a de prise ; le segment, le contexte et « dans la vidéo
  finale » sont dans « Réglages de la branche ». ⚙ Réglages du plan ne garde que ce qui reste libre.
- **En-tête de branche** : un seul bouton « réglages… » remplace « références… », « LoRA… » et
  « Upscale… ».
- **« Importer un plan… »** : seulement dans l'en-tête de l'écran du plan maître ; remplace le plan maître
  de la branche après confirmation ; grisé si la branche a des prises, avec l'infobulle « créer une
  nouvelle branche à partir d'un fichier de plan ».
- **↻ nouvelle prise…** aussi sur une génération en file ou en cours : le panneau est pré-rempli d'après la
  génération (graine, prise précédente, LoRA, upscale, clip lancé). La nouvelle prise suit la même prise
  précédente et ne dépend pas de la génération en cours.

## 11. Projet et branches : ce qui appartient à qui (décidé le 23/11, remplace § 3.1 et une partie du § 10)

Le projet porte l'essence de la vidéo ; les branches ne portent que des variations de méthode, de prompt et de
références.

| Projet (« Réglages du projet ») | Branche (« Réglages de la branche » et plan maître) |
|---|---|
| Mode : clip musical ou libre | Taille d'image |
| Vidéo : aucune, continuer ou éditer (éditer : mode libre) | Segment de la vidéo (plan maître, ⚙ Réglages du plan) |
| Fichier de la vidéo | Fichiers des références déjà utilisés |
| Chanson (clip musical) | Taille des références, LoRA, upscale (toujours libres) |
| Contexte | |

- **Projet** : modifiable tant que le projet n'a aucune prise (toutes branches confondues), puis grisé avec
  la raison. Tant qu'il n'a aucune prise, importer un plan ou enregistrer un plan maître adopte son mode, sa
  vidéo et son contexte pour tout le projet ; ensuite, ils sont imposés aux plans enregistrés ou importés.
- **Branche** : la taille, le segment et les fichiers des références déjà utilisées se figent avec la
  première prise de la branche (ou les clips qu'elle reprend) ; une branche dupliquée avec ses clips garde le
  segment de sa source.
- **Écran des prises** : la colonne « Vidéo de départ » montre le segment de chaque branche.
- **Clip suivant** : une case « + clip suivant » suit toujours une prise sans suite. Le panneau est pré-rempli
  avec le clip suivant du plan de la brindille, sinon du plan maître, sinon une copie complète du clip
  d'avant (prompt, durée, références, répliques), avec un nouveau nom et le lien ↪ continue (décidé le 23/11,
  livré avec A3).
- La barre de sélection et son bouton « Plan de la sélection… » restent tels quels.

## 12. Lot A3 : ce qui a été fait (0.44)

- 🗑 au survol d'une prise : elle part avec les prises faites après elle (chaîne des prédécesseurs, toutes
  branches). Une branche qui la reprenait garde les clips d'avant. Refusé si une génération en file en dépend.
- Supprimer une branche garde les prises qu'une autre branche reprend.
- Corbeille par projet (`trash/`) : un élément par suppression, restauré en entier ou effacé ; « Vider ».
  La restauration est refusée si une prise dont elle a besoin n'est plus là (restaurer d'abord l'élément qui la
  contient) ou si la branche de ses prises a été supprimée.
- Ctrl+Z / Ctrl+Y seulement sur l'écran de plan et dans le panneau de lancement.
- Le panneau de lancement se pose par-dessus l'écran des prises ; la minimap montre aussi la zone de scroll sous
  la dernière branche.

## 13. Après le chantier (0.45, décidé le 24/11)

- « Utiliser ce plan… » (plan d'une sélection) : le plan devient le plan maître de sa branche (l'ancien à la
  corbeille, restaurable : la restauration échange les deux) ou d'une nouvelle branche avec les réglages de
  celle-ci, sans clip repris.
- Une génération en file ou en cours se sélectionne comme une prise (son identifiant est connu au lancement).
