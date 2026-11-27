# Historique des versions

Versions d'Encore (appelé H3 Studio jusqu'à la 0.16). Chaque version est livrée sous la forme
`Encore_vX.Y.zip`. Depuis la 0.50, Encore n'a plus besoin du plugin ComfyUI ComfyUI-H3-ClipPlan (jusqu'à la
0.49 : 4.0 ou plus récent).

## 0.50

**Encore sans ComfyUI-H3-ClipPlan.** ComfyUI fait toujours toute l'inférence ; Encore compose, prépare les
fichiers et envoie à ComfyUI des workflows faits de ses nœuds natifs et de ceux de MultiRef et VideoHelperSuite.

- **Le workflow d'un clip** : MiniMax H3 Reference to Video (natif) reçoit le prompt composé par Encore (celui
  de l'onglet « Prompt H3 »), ses images (Load Image) et ses voix (Load Audio) ; le latent à échantillonner est
  préparé par les nœuds de MultiRef : la fin de la prise continuée (Load Latent + contexte AV généré), la
  chanson (contexte de chanson), la fin de la vidéo de départ (contexte de vidéo existante) ; un clip édité
  donne sa tranche de vidéo comme vidéo de référence (VHS Load Video), avec son son. La prise est enregistrée
  par MultiRef (Save Latent, un fichier `.safetensors`), son aperçu par VHS. Les noms des entrées multiples du
  nœud de référence sont lus dans `/object_info` de ComfyUI. Le latent upscale ne change pas.
- **Fichiers préparés par Encore avec ffmpeg** (gardés dans `cache/comfy/` du projet) : les voix coupées aux
  limites de H3 (2 à 15 s chacune, 15 s en tout), la chanson précédée de silence quand elle commence après le
  plan, la fin de la vidéo de départ et la tranche d'un clip édité à la taille de la branche.
- **La fiche d'une prise** est écrite par Encore ; le latent et l'aperçu sont récupérés dans ComfyUI à la fin.
  Côté ComfyUI, tout est sous `input/encore/…` et `output/encore/<projet>/` ; c'est vidé quand plus aucune
  génération n'attend, seulement si le dossier de ComfyUI est connu (ComfyUI ne sait pas supprimer de fichiers
  par son API : avec un ComfyUI sur une autre machine, ils restent, les réglages le disent).
- **Prises faites avant la 0.50** : leur latent `.pt` (écrit par le plugin) est réécrit une fois au format de
  MultiRef à l'ouverture du projet, avec une fenêtre de progression (simple réécriture de fichiers, sans
  torch). Une prise qui ne peut pas être convertie reste visible et assemblable, mais ne peut pas être
  continuée.
- **Assemblage** : par Encore avec ffmpeg uniquement, à partir des aperçus des prises ; une prise sans aperçu
  n'est pas assemblée (il faut la refaire). Le nœud d'assemblage du plugin ne sert plus.
- **Écran d'installation** : ComfyUI-H3-ClipPlan n'est plus dans la liste ; MultiRef et VideoHelperSuite restent
  obligatoires (avec les nœuds désormais utilisés) ; le ffmpeg trouvé par Encore est affiché ; un dossier
  ComfyUI-H3-ClipPlan encore dans `custom_nodes` est signalé (plus utilisé ; à garder si vous vous en servez
  dans ComfyUI).
- **Le format de plan est celui d'Encore** : `docs/PLAN_SPEC.md`, `docs/plan.schema.json`, et le prompt système
  pour faire écrire un plan par un modèle de langage, `docs/LLM_SYSTEM_PROMPT.md` (avec sa règle 12 sur la
  continuité : un mouvement qui quitte quelque chose puis y revient reste dans un même clip). Les exemples du
  robot sont dans `examples/`.
- Tests : le faux ComfyUI a de faux nœuds natifs, MultiRef et VHS (il ne fait plus tourner le plugin).


## 0.49.1

- **↻ nouvelle prise part d'une nouvelle graine** (tirée au hasard, 🎲 pour une autre). « ↺ graine de la prise
  refaite » remet sa graine ; avec le même prompt, Encore prévient toujours que la prise sera identique.

## 0.49

**Portions reprises dans une duplication.** « dupliquer » avec des clips ne reprend plus seulement les clips 1 à k :

- La fenêtre montre la sélection en petites vignettes, scène par scène (✂ entre elles). Un clic reprend un clip
  avec sa scène depuis son début, ou le laisse libre avec la suite de sa scène : les portions gardent toujours
  leur continuité (un clip qui en continue un autre n'est repris qu'avec lui). « Tout reprendre » par défaut.
- La nouvelle bande montre les clips repris et une case vide pour chaque clip laissé libre ; les clips repris
  après elle s'y accrochent. ▶▶ compléter ne fait que les clips laissés libres ; l'assemblage de la ligne passe
  par les clips repris après eux.
- Les clips laissés libres partent du plan de la sélection et restent modifiables dans le plan maître, comme
  les clips après k jusqu'ici : la ligne du plan maître les fige en les générant. Seuls leur durée et leur lien
  (↪/✂) sont verrouillés, dans le plan maître et dans le panneau de lancement, pour que les portions d'après
  restent à leur moment de la chanson ; le serveur refuse une autre durée.
- Un clip repris après un clip laissé libre suit la prise de ce clip faite dans la branche (celle de la
  sélection, sinon celle de sa ligne du plan maître) ; tant qu'elle n'existe pas, ses ↻ et + sont grisés.

## 0.48.2

- **Images à fournir** : une image qu'un plan importé déclare sans fichier s'affiche en cadre pointillé avec son
  label et sa note, au lieu d'une image cassée. Choisir une image du projet ou en importer une de l'ordinateur
  (ou la déposer) : le label reçoit le fichier, garde son nom, sa note et son rôle, et les clips qui l'utilisent
  restent justes. Un clic sur la vignette d'une image la remplace, rôle conservé. La bibliothèque a une section
  « Images à fournir ».
- **Import par glisser-déposer** depuis l'ordinateur : sur la fenêtre Ressources (un fichier audio va dans la
  section où on le dépose, sinon Encore demande voix ou chanson), sur « Fichiers du projet », sur la fenêtre du
  sujet (images, voix) et sur « Images à fournir ». Le choix d'image importe directement, sans passer par
  Ressources.
- **↻ nouvelle prise et + clip suivant sur un clip repris** d'une autre branche : la nouvelle prise est une
  variante de la branche dupliquée ; la branche d'origine ne change pas.
- **Panneau de lancement, « Plan des clips suivants »** : un choix par plan distinct (et non par brindille),
  avec les prises de la brindille en vignettes (la nouvelle prise en pointillé) et une étiquette jaune de ce qui
  change (« clip 3 modifié »). Masqué quand toutes les brindilles gardent le même plan.
- **File d'attente** : un groupe se déplace par sa poignée ≡, une ligne montre où il arrive, la liste défile à
  ses bords ; « Voir les n tâches » s'ouvre de nouveau.
- La minimap dessine le graphe depuis le haut ; l'étiquette du panneau replié des vidéos assemblées ne
  clignote plus.
- Corrigé : déposer un fichier sur Encore ne propose plus de l'ouvrir comme plan (« les modifications non
  enregistrées seront perdues »).

## 0.48.1

- Corrigé : après « Enregistrer le plan », le plan affiché sur l'écran de plan disait version 3, et ses
  contrôles affichaient « 'version' must be 7 » (le plan enregistré sur le disque était correct).

## 0.48

**Le plan maître comme patron de départ, la ligne du plan maître.** Une branche a un plan maître et une ligne du
plan maître ; les brindilles sont libres d'évoluer.

- **Ligne du plan maître** : les prises faites à partir du plan maître lui-même, une par clip, en ligne en haut
  de la bande (étiquette « plan maître »), suivies de cases vides pour les clips pas encore générés. La première
  case vide (▶) ouvre le panneau de lancement de ce clip (en lecture seule ; graine, LoRA, upscale se règlent) ;
  une case se génère une seule fois, dans l'ordre. Un changement passe par
  « ↻ nouvelle prise… », qui fait une variante. Après une prise de la ligne vient le plan maître lui-même.
- **▶▶ compléter** (en-tête de branche) remplit la ligne du plan maître. **▶▶ compléter la sélection** (barre
  de sélection) génère la suite du plan de la brindille sélectionnée.
- **Le plan maître est figé dès que la branche a une prise** (ou une génération en attente) : ses clips et ses
  sujets (avec les fichiers qu'ils utilisent) sont en lecture seule — 🔒 sur les clips et dans la bibliothèque ;
  la fenêtre d'un sujet figé n'a pas « Enregistrer ». On peut ajouter des clips à la fin (libres tant que la
  ligne ne les a pas générés) et de nouveaux sujets. Le serveur refuse tout autre changement.
- **dupliquer** dans l'en-tête de branche : sans les clips (le plan maître de la copie redevient libre) ou avec
  les clips 1 à k de la sélection. **+ nouvelle branche** garde « Vide » et « À partir d'un fichier de plan… ».
- **« Utiliser ce plan… » devient « Nouvelle branche avec ce plan… »** : un plan maître n'est jamais remplacé
  quand sa branche a des prises.
- Écran des prises : les arbres sont alignés en haut (le premier enfant d'une prise est sur sa ligne), la ligne
  du plan maître est donc droite.
- Écran de plan : l'onglet « Prompt H3 » d'un clip généré ou figé se lit.
- Projets d'avant : leurs branches avec des prises ont leur plan maître figé tel qu'il est ; leur ligne du plan
  maître est vide (ses cases peuvent être générées).
- Tests : nouveaux `d1_api_test`, `d2_ui_test` ; `a2_ui_test` et `a3_api_test` suivent les changements.

## 0.47

L'écran des prises et l'écran de plan, remis en ordre.

- **Branche repliée** : plus de ▶▶ dessus ; replier la branche de la sélection fait passer la sélection à
  la première brindille (ligne du haut de l'arbre) de la première branche dépliée.
- **◎ Génération en cours** (barre du haut de l'écran des prises) : amène la prise en cours de génération
  au milieu de la vue, en dépliant sa branche.
- **Le nom d'une branche est un champ** : taper le nouveau nom, Entrée ou un clic ailleurs l'enregistre,
  Échap remet l'ancien. Plus de bouton « renommer ».
- **Vue d'ensemble** : le graphe seul la remplit, centré, comme dans ComfyUI ; le cadre de la vue est coupé
  à ses bords quand la vue dépasse le graphe. La sélection est dessinée en bleu, liens compris, sur toute
  la brindille.
- **Le défilement vers le bas s'arrête** quand la prise la plus basse arrive en haut de la vue.
- **Les vidéos assemblées s'ouvrent au double-clic**, comme les prises. **Toute vidéo ouverte en grand
  tourne en boucle.**
- **Mode colonnes retiré** : les prises sont toujours affichées en arbre.
- **Barre du haut de l'écran des prises** : le libellé « 1 en cours · n en attente » et le bouton Arrêter
  disparaissent (l'indicateur de la file dit tout). **Tout annuler** dans le gestionnaire de la file
  (toutes les tâches de tous les projets, après confirmation).
- **Assemblage avec le volet des vidéos replié** : un message dit qu'il est ajouté à la file, et l'onglet
  replié montre les assemblages en attente ou en cours.
- **Indicateur de la file** : largeur fixe ; un texte trop long finit par « … », le texte entier est dans
  l'infobulle.
- **Barre de progression d'une génération** : en bas de sa vignette, plus sous « nouvelle prise » et
  « annuler ».
- **Écran de plan** : une ligne à lui sous celle du projet : « ← Prises », le titre (● tant que des
  modifications ne sont pas enregistrées), ⚙ Réglages du plan, Importer / Utiliser ce plan, puis
  ↶ Annuler, ↷ Rétablir et Enregistrer le plan, avec leur nom. Les boutons du projet restent sur la ligne
  du dessus. Le titre ne montre plus la chaîne des identifiants de prises (elle apparaissait deux fois).
- Tests : nouveau `c1_ui_test` ; `v29_test` suit les nouvelles règles de repliement.

## 0.46

**Sujets, fichiers et ancres** (chantier B). L'écran de plan ne demande plus d'écrire dans la forme propre à
MiniMax : Encore la compose. **Les plans des versions précédentes sont refusés** (plans version 7 seulement) ;
nécessite ComfyUI-H3-ClipPlan **4.0**.

- **Les sujets** (personnage, lieu, objet, tenue, style, action, pose) sont gérés dans le plan, avec une
  description, autant d'images que nécessaire (chacune avec ce qu'elle apporte) et, en mode libre, une voix.
  On les nomme `@nom` dans des champs simples : Résumé, Plans, Son, Musique. **Les fichiers** sont ceux du
  projet : le plan les nomme par une étiquette faite automatiquement. Les branches n'ont plus de références
  à elles : leurs plans maîtres portent les sujets et leurs images.
- **Ancres** d'un clip : première image, images clés à une seconde donnée, dernière image.
- **Sujets du clip** : la fidélité de chacun (images, voix) et une note pour ce clip seulement. Un compteur
  par rapport aux limites de H3 (9 images, 3 voix, 12 fichiers).
- **Onglet « Prompt H3 »** : le prompt que reçoit MiniMax H3, composé par Encore (numéros des sujets, images
  et voix, définitions, rétention, préfixe de tâche, phrase d'ouverture d'une continuation ou d'une nouvelle
  scène), avec des pastilles qui donnent chaque numéro. Il peut être **écrit à la main** (`@nom` reçoit
  toujours son numéro) ; « Revenir au prompt composé » l'annule.
- **Locuteurs des répliques trouvés tout seuls** : le sujet nommé dans la phrase d'une réplique, ou celui du
  dialogue dont le texte correspond ; numérotés S1, S2… dans l'ordre où ils parlent. `@nom (S)` seulement
  pour choisir un autre locuteur.
- **« / » pour la caméra** : le vocabulaire de MiniMax pour les mouvements (avec amplitude et vitesse), les
  coupes et les cadrages, écrit en anglais à l'endroit du curseur.
- **Un clip généré garde ses sujets et fichiers** tels qu'ils étaient à sa génération, même si le plan les
  change ensuite (fenêtres ≡, plan de la sélection, branches qui reprennent des clips).
- **Consigne commune d'une édition** : les sujets nommés avec `@` ; elle ouvre le résumé des clips édités.
- **Ressources** : chaque fichier dit s'il est utilisé, utilisé seulement par des prises, ou inutilisé ;
  **Supprimer les inutilisés** les supprime d'un coup.
- **Supprimer un projet** (🗑 sur sa carte, ☰ Projets) : définitivement, après une confirmation qui compte
  ses prises, ses vidéos assemblées et sa taille ; ses copies dans ComfyUI partent aussi. Refusé tant
  qu'une de ses générations ou assemblages attend ou tourne.
- **▶▶ compléter** n'est plus grisé pendant une génération.
- Corrigé : un clip ajouté après le segment d'une vidéo éditée gardait `<Video 1>` dans ses textes.
- Développement : `plan_core.compose_clip` (identique dans le plugin), `snapshot_defs`, `preview`
  (`POST /plan/compose`), `resources.usages` et `delete_unused`, `projects.delete_project` ; nouveaux tests
  `b1_api_test`, `b2_ui_test` ; `sha_test` et `roundtrip_test` retirés.

## 0.45.1

- README : nouvelles captures (écran des prises, panneau de lancement, plan de la sélection, fenêtre de plan,
  file) ; le script des captures remarche (la chanson est celle du projet depuis la 0.43). Aucun changement de
  l'application.

## 0.45

- **« Utiliser ce plan… »** sur le plan d'une sélection : son plan (les clips générés tels qu'ils ont servi, puis la
  suite) devient **le plan maître de sa branche** (l'ancien part à la corbeille, d'où il revient d'un clic) ou le plan
  maître d'**une nouvelle branche** avec les réglages de cette branche (aucun clip repris, tout à générer ; la branche
  courante ne change pas). Pour essayer dans d'autres branches des prompts qui marchent.
- **Une génération encore en file ou en cours se choisit** d'un clic, comme une prise : la sélection passe par la
  prise qu'elle fera ; « Plan de la sélection… », « Utiliser ce plan… » et « ▶ assembler » (planifié après elle)
  marchent sans attendre. Une fois faite, la prise reste choisie.
- Développement : `projects.use_twig_plan`, `trash.replace_master` ; la brindille d'une sélection peut passer par
  une prise pas encore faite (`plans.PENDING`). Tests dans `a3_api_test`, `a3_ui_test`.

## 0.44.1

- Corrigé : les **Réglages du projet** (modèle de diffusion, échantillonnage, pile de LoRA, aperçus…) ne
  s'enregistraient plus depuis la 0.42 (« internal error … save_settings »), et « Reprendre les réglages par
  défaut » échouait de la même façon. Un test change maintenant le modèle d'un projet et vérifie que la génération
  suivante l'utilise.

## 0.44

**Supprimer et la corbeille** (chantier A, lot 3).

- **🗑 sur une prise** (au survol) : la supprime avec toutes les prises faites après elle, dans toutes les
  branches. La confirmation les liste par clip, et dit ce que garde une branche qui reprenait la prise (« « Branche
  3 » ne gardera que les clips 1 à 2 »). Refusé tant qu'une génération en file ou en cours a besoin de l'une d'elles.
- **Supprimer une branche** ne supprime plus les prises qu'une autre branche reprend : elles restent, montrées dans
  cette branche.
- **Corbeille** (bouton « Corbeille… » du projet) : rien n'est effacé quand on supprime. Une prise avec sa suite, ou
  une branche avec ses prises, son plan maître et ses vidéos assemblées, y attend : **Restaurer** la remet en entier
  (et les clips que d'autres branches reprenaient) ; **Effacer** ou **Vider la corbeille** supprime les fichiers
  pour de bon.
- **Ctrl+Z / Ctrl+Y** seulement là où l'on modifie le plan (écran de plan, panneau de lancement) : plus de
  modification du plan par mégarde depuis l'écran des prises.
- **« + clip suivant »** sans clip prévu (ni dans la sélection ni dans le plan maître) : une copie du clip précédent
  (prompt, durée, références, répliques), qui le continue (↪).
- **Le panneau de lancement se pose par-dessus l'écran** : les prises et les vidéos assemblées ne bougent plus ; la
  prise de départ est amenée à côté de lui, et la vue revient à sa fermeture.
- Corrigé : scrollée tout en bas (dernière branche en haut de la vue), le cadre de la vue d'ensemble en sortait.
- Développement : nouveaux `encore/trash.py` et `ui/plan_trash.js` ; nouveaux tests `a3_api_test`, `a3_ui_test`.

## 0.43

**Branches** (chantier A, lot 2). Les projets des versions précédentes ne sont pas convertis.

- **Le projet porte ce qu'est la vidéo ; les branches portent les variations.** Le mode (clip musical ou libre),
  la vidéo (aucune, continuer, éditer) et son fichier, la chanson et le contexte se règlent dans **Réglages du
  projet**, les mêmes pour toutes les branches, et se figent avec la première prise du projet. Une branche garde sa
  taille d'image, le segment de la vidéo (dans son plan maître), ses fichiers de références, ses LoRA et son upscale.
- **Fenêtre « Nouvelle branche »** : vide, **à partir d'un fichier de plan**, ou **dupliquer une branche** — sans
  clips, ou **en reprenant les clips 1 à k de la sélection** (par référence, rien n'est copié : ils apparaissent
  estompés, « ⇡ Branche 1 », et on génère à partir du clip k+1). La fenêtre dit quelles références restent figées
  (utilisées par un clip repris).
- **Fenêtre « Réglages de la branche »** (un bouton « réglages… » au lieu de références…, LoRA…, upscale…) : ce que
  les prises figent est grisé dès l'ouverture, avec une infobulle qui dit pourquoi et comment faire (dupliquer la
  branche) ; plus de refus après coup. Pareil dans les réglages du plan (segment) et du projet.
- **Les nouvelles scènes (✂) suivent de nouveau la sélection**, comme avant la refonte : une prise ✂ se rattache à
  la prise sélectionnée avant elle si elle y commence au même moment de la chanson (en mode libre : toujours). Plan
  de la sélection, ▶▶ et assemblages suivent.
- **« + clip suivant » après toute prise sans suite**, même au-delà de la fin du plan : le panneau est pré-rempli
  avec le clip suivant du plan de la sélection, sinon du plan maître, sinon un nouveau clip qui reprend le précédent.
- **↻ nouvelle prise…** aussi sur une génération encore en file ou en cours.
- **Importer un plan…** seulement sur l'écran du plan maître d'une branche, grisé dès qu'elle a des prises (créer une
  branche à partir du fichier). Tant que le projet n'a aucune prise, un plan importé ou enregistré fixe son mode, sa
  vidéo et son contexte.
- Corrigé : le panneau de lancement montrait les images de la branche sélectionnée au lieu des siennes.
- Développement : nouveau `ui/plan_branch.js` ; `plans.cut_fits`, `plans.fits_map`, `projects.new_branch`,
  `projects.set_essence` ; nouveaux tests `a2_api_test`, `a2_ui_test`, `unit/cuts_test.py`.

## 0.42

**Chaque brindille a son propre plan** (chantier A, lot 1). Les projets des versions précédentes ne sont pas
convertis : partir de nouveaux projets.

- **Une prise ne se périme plus.** Chaque branche a un **plan maître** ; chaque prise enregistre le plan de ce qui
  la suit. Le plan d'une brindille (une prise et celles qu'elle continue), c'est la partie figée de chacune de ses
  prises, puis le plan qui suit sa dernière prise. Modifier le plan maître ou le plan d'une brindille ne change
  rien pour les autres. Les prises invalidées (rayures jaunes), ⟲ refaire et l'assemblage de prises invalidées
  disparaissent.
- **L'écran des prises devient l'écran principal.** L'onglet Plan est remplacé par un écran de plan ouvert depuis
  lui : **plan maître…** (en-tête de branche) ou **Plan de la sélection…** (nouvelle barre de sélection au-dessus
  du graphe), retour par **← Prises**. Dans le plan d'une sélection, les clips déjà générés portent 🔒 et sont en
  lecture seule ; on peut ajouter ou modifier des clips après eux.
- **Panneau de lancement** : **↻ nouvelle prise…** et **+ clip suivant…** ouvrent un panneau par-dessus les
  prises : de quelle brindille partir (quand plusieurs passent par la prise ; le survol la surligne), graine (une
  nouvelle prise garde la graine de la prise qu'elle refait, 🎲 pour une graine au hasard, avertissement si la
  prise serait identique ; le clip suivant reçoit une graine au hasard), LoRA et upscale de la prise, et le clip
  dans l'éditeur de plan. Il remplace la fenêtre « prise réglée » (▾).
- **La sélection est une brindille** : cliquer une prise la sélectionne avec celles qu'elle continue. ▶▶ complète
  la brindille sélectionnée jusqu'à la fin de son plan ; ▶ assembler 1–k assemble la brindille de la prise.
- **Figé dès qu'une branche a une prise** : sa taille, sa chanson, les fichiers de ses références déjà utilisées,
  et les réglages du plan dont dépendent les prises (mode, vidéo de départ ou éditée, contexte). La vidéo de
  départ ne se change que tant qu'aucune branche n'a de prise. Les options d'assemblage restent libres.
- **Importer un plan…** va dans une branche : il remplace le plan maître d'une branche sans prise, sinon il crée
  une nouvelle branche. Les graines du fichier sont ignorées. Un nouveau projet part avec « Branche 1 » ; une
  nouvelle branche copie le plan maître de la dernière.
- **Retirés** : les points de sauvegarde (et la limite de points automatiques de la page d'accueil), les LoRA par
  clip (⚙ d'une colonne de clip). Supprimer une branche supprime définitivement ses prises, ses plans et ses vidéos.
- Développement : nouveaux `encore/plans.py` et `ui/plan_launch.js` ; `encore/checkpoints.py` supprimé ;
  nouveaux tests `a1_api_test`, `a1_ui_test` ; `v24_test` et `v24_ui_test` supprimés. Plugin inchangé (3.11).

## 0.41

Aucun changement de comportement : réorganisation du code pour la maintenance.

- `encore/engine.py` (2 400 lignes) perd ses parties sans état, déplacées dans leurs propres fichiers :
  `encore/workflows.py` (workflows ComfyUI, upscale latent, nœuds manquants), `encore/exports.py` (vidéos
  assemblées : noms, fiches d'information, liste) et `encore/diagnostic.py` (diagnostic des aperçus). Le code
  déplacé est inchangé.
- Nouveau [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) : quel fichier fait quoi, les sections du moteur et son
  état partagé, où intervenir pour une évolution, et quels tests lancer pour chaque fichier.
- Les images des tests (`tests/fixtures/*.png`) sont de retour dans l'archive livrée : elles manquaient dans
  celle de la 0.40.

## 0.40

- **Retour arrière sur l'édition de vidéo : elle refonctionne comme en 0.38** (plugin 3.11). La correction de
  netteté de la 0.39 cassait la cohérence entre clips (par exemple la robe rouge qui disparaissait au clip 2) :
  la vidéo de référence redevient la vidéo d'origine sur toute la durée, Encore n'envoie plus l'aperçu des
  prises à ComfyUI. Les prises faites en 0.39 pour des clips d'édition qui en continuent un autre sont
  périmées. Pour le rendu final d'une édition, éviter l'upscale latent.
- **Nouveau : la vidéo finale est assemblée par Encore avec ffmpeg**, à partir des aperçus des prises, sans
  passer par la file de ComfyUI ni redécoder les latents. Elle peut se faire pendant qu'une génération tourne.
  Même résultat que l'assemblage du plugin : recouvrements retirés (ou fondus), vidéo de départ, chanson, son
  de chaque prise en mode libre, son d'origine sur la partie éditée. La file affiche « assemblage (ffmpeg)… N % ».
  Si une prise n'a pas d'aperçu ou si ffmpeg est introuvable, le plugin assemble comme avant ; on peut aussi le
  forcer avec `"assembly_engine": "plugin"` dans config.json. Le fichier d'infos de la vidéo dit qui l'a faite.
  Les aperçus sont réencodés au crf réglé.
- Gardé de la 0.39 : dans l'onglet Prises, la dernière branche remonte jusqu'en haut de la vue.

## 0.39

- **Corrigé : les vidéos éditées perdaient en netteté clip après clip** (surtout avec un upscale latent). Un clip
  d'édition qui continue le précédent reçoit maintenant, au début de sa vidéo de référence, les images de la
  prise qu'il continue au lieu de la vidéo d'origine : H3 n'est plus tiraillé entre les deux (plugin 3.10).
  Encore envoie l'aperçu de la prise à ComfyUI avec son latent quand il le faut. Les prises des clips d'édition
  qui en continuent un autre, faites avant, sont périmées : il faut les régénérer.
- Onglet Prises : en bas du défilement, la dernière branche remonte maintenant jusqu'en haut de la vue (elle
  restait collée au bas de l'écran).

## 0.38

- **Nouveau, vidéo éditée : la consigne commune.** L'édition commune aux clips s'écrit une fois, dans
  « ✎ Consigne commune », la première entrée de la liste des clips (dans son propre éditeur, avec les
  références à droite : en glisser une ou taper `@`), et se met dans les prompts sous la forme `{edit}`
  (« Découper sur les plans » le fait ; plus de TODO). Une image qu'elle cite est ajoutée à chaque clip qui
  l'utilise. L'entrée dit quels clips l'utilisent, lesquels ont leur propre texte, et montre ce que H3
  reçoit ; les réglages l'affichent sur une ligne. Demande le plugin 3.9.
- **Nouveau, vidéo éditée : continuer après le segment.** Les clips qui finissent après la fin du segment
  continuent la vidéo au lieu d'être une erreur : la frise montre la fin du segment, les clips édités ont
  🎞, les réglages disent quels clips éditent et lesquels continuent. Un clip ajouté après le segment reçoit
  un prompt neuf (pas de `<Video 1>`, qui y est une erreur). « Découper sur les plans » garde ces clips.
  Avec le son d'origine, la vidéo finale le garde sur la partie éditée seulement.
- L'onglet « Aperçu envoyé à H3 » montre `{edit}` remplacé.
- Les plans sont enregistrés en version 6 (envoyés en version 6 quand ils éditent une vidéo, en version 4
  sinon).

## 0.37

- **Nouveau : éditer une vidéo existante** (mode libre ; demande le plugin 3.8). Dans ⚙ Réglages du plan, la
  section « Vidéo » propose « Pas de vidéo / Continuer une vidéo / Éditer une vidéo ». En édition, la frise du
  plan est le segment choisi et chaque clip édite son propre morceau, donné à H3 comme `<Video 1>` avec son
  son ; les voix du clip sont numérotées après. La vidéo finale garde le son d'origine du segment (par défaut)
  ou le son fait par H3.
- **✂ Découper sur les plans** : les changements de plan du segment sont trouvés (ffmpeg) et les clips créés
  à partir d'eux : une nouvelle scène à chaque changement de plan, les plans longs coupés en parts égales qui
  s'enchaînent, clips d'au plus 10,1 s par défaut. Chaque clip reçoit un prompt qui garde le cadrage, les
  mouvements et le rythme de `<Video 1>` ; il ne reste qu'à écrire l'édition (TODO).
- Les branches sont averties quand elles n'ont pas les proportions de la vidéo, et les reçoivent à la demande.
- Onglet Prises : la carte vide d'un clip montre la partie de la vidéo qu'il édite (survol : elle se lit).
- Les plans sont enregistrés en version 5 ; ceux sans vidéo éditée sont envoyés à ComfyUI en version 4, pour
  que le plugin 3.7 les lise encore.

## 0.36

- **Corrigé** : la carte de la vidéo de départ de l'onglet Prises mettait du temps à s'afficher (elle chargeait
  tout le fichier vidéo), était rechargée à chaque redessin de l'onglet (une nouvelle prise les
  réinitialisait toutes) et pouvait continuer à jouer sans la souris dessus. Elle joue maintenant une petite
  copie du segment seul (270 pixels de haut, son conservé), faite une fois par ffmpeg en arrière-plan (la carte
  affiche « préparation… » en attendant) et refaite quand la vidéo ou le segment change ; ça marche aussi pour
  les vidéos que le navigateur ne sait pas lire. Le même lecteur est gardé quand l'onglet est redessiné, et il
  est arrêté comme les vignettes des prises quand il joue sans la souris dessus. Sans ffmpeg, la carte joue le
  fichier lui-même à partir du début du segment. Les cartes des vidéos assemblées du graphe gardent aussi leur
  lecteur. Supprimer la vidéo supprime ses copies.

## 0.35

- **Corrigé** : dans l'onglet Prises, avec plus de vidéos assemblées que la colonne de droite ne pouvait en
  contenir, leurs vignettes étaient écrasées en fines bandes et la colonne ne défilait pas. Elles gardent
  maintenant leur taille et la liste défile (ascenseur et molette).

## 0.34

- **Corrigé** : un gros fichier (une vidéo, typiquement) était refusé par ComfyUI (« 413 … Maximum request
  body size 104857600 exceeded ») : sa route d'envoi accepte 100 Mo au plus par défaut. Quand le dossier de
  ComfyUI est connu, Encore copie maintenant les fichiers directement dans le dossier `input` de ComfyUI (et
  les prises dans `output`), sans limite de taille, la progression toujours affichée dans la file. Sinon la
  route d'envoi reste, et un refus dit maintenant quoi faire : indiquer le dossier de ComfyUI, ou lancer
  ComfyUI avec `--max-upload-size 4096`.
- **Nouveau** : une vidéo que le navigateur ne sait pas lire (AVI, ProRes, HEVC… ; le lecteur restait gris)
  reçoit une copie légère lisible (H.264, 540 pixels de haut au plus, son conservé), fabriquée par ffmpeg avec
  sa progression sous le lecteur (annulable). Les lecteurs des réglages du plan et des ressources l'utilisent ;
  ComfyUI reçoit toujours l'original. ffmpeg est celui d'imageio-ffmpeg dans le Python de ComfyUI (celui du
  plugin), sinon celui du PATH. Supprimer la vidéo supprime sa copie.

## 0.33

- **Corrigé** : avec l'upscale activé, le clip 1 qui continue la vidéo de départ perdait la vidéo en deuxième
  passe : les dernières images de la vidéo n'y étaient pas remises (ni protégées), la deuxième passe les
  redessinait à partir de la première passe floue et le personnage pouvait devenir un personnage approchant mais
  différent. Elles sont maintenant remises en deuxième passe, comme pour les clips qui en continuent un autre.

## 0.32

- **Corrigé** : le bouton 🗑 d'une ressource était caché quand le nom du fichier était long (il était coupé avec le
  nom). Il reste maintenant visible : dans le coin de la vignette, ou en bout de ligne.

## 0.31

- **Vidéo de départ, tout dans les réglages du plan** : la vidéo se choisit (ou s'importe) dans ⚙ Réglages du
  plan > Vidéo de départ, une pour le projet, utilisée par toutes les branches. Ce n'est plus une référence des
  branches ni de la liste des références du plan. La changer demande confirmation si des prises du clip 1
  l'utilisent.
- **Colonne Vidéo de départ** dans l'onglet Prises, avant le clip 1, quand le segment ouvre la vidéo finale : le
  segment dans chaque branche, relié aux prises du clip 1 qui le continuent (survol : il se lit ; clic : ses
  réglages).
- **Gros fichiers** : un import affiche une fenêtre de progression (fichier, %, Mo, annuler) et s'écrit au fil de
  l'eau, sans être gardé en mémoire ; les fichiers partent vers ComfyUI par morceaux, la file affiche l'avancement.
- **Supprimer des ressources** (🗑 dans Ressources) : refusé tant qu'une branche ou la vidéo de départ utilise le
  fichier, après un avertissement si seuls des points de sauvegarde ou des prises en ont besoin. La copie dans le
  dossier input de ComfyUI part aussi. Taille totale affichée.
- Les points de sauvegarde gardent aussi la vidéo de départ.
- **Corrigé** : « null » écrit dans les réglages du plan (mode libre, vidéo de départ).

## 0.30

- **Partir d'une vidéo existante** : dans ⚙ Réglages du plan, « Vidéo de départ » : le clip 1 continue un
  segment d'un fichier vidéo (même plan) ou coupe après lui. La vidéo s'importe dans Ressources (nouvelle
  section « Vidéos ») et se choisit par branche dans « références… ». Le segment se choisit dans un lecteur
  (« ⇤ ici » / « ici ⇥ », « ▶ lire le segment ») et s'aimante sur la grille des images. Option : le segment
  ouvre la vidéo finale, ou ne sert que de tremplin. Clip musical : la chanson commence avec la vidéo (par
  défaut) ou après elle (la vidéo garde son propre son). Le segment apparaît sur la frise de l'onglet Plan et
  dans l'en-tête de la branche.
- Changer le fichier vidéo de la branche ou le segment invalide les prises du clip 1 et celles qui les
  continuent.
- **Demande ComfyUI-H3-ClipPlan 3.7** : les plans passent en version 4 (l'écran d'installation demande la mise
  à jour).

## 0.29

- **Branches repliées** : elles ont toutes la même largeur, les boutons ▶▶ alignés à droite ; plus de
  libellé « · sélection ».
- **Une branche repliée n'a jamais la sélection** : replier la branche de la sélection la fait passer à
  une branche dépliée (celle de la dernière prise valide du clip 1), et une prise finie dans une branche
  repliée n'est pas choisie d'office.
- **Au moins une branche reste dépliée** : la flèche de repli de la dernière est grisée.
- **Pour le dépôt GitHub** : un README avec le logo, des captures d'écran et un démarrage rapide, la licence
  GPL-3.0, et `tests/screenshots/` qui fait les captures.

## 0.28

- **Upscale d'une prise, plus simple** : la fenêtre « prise réglée » (▾) n'a plus le choix « selon la
  branche / avec / sans ». Elle montre les réglages d'upscale de la branche sur une ligne repliée
  (« comme la branche « X » ») ; **modifier…** déplie le formulaire complet pour les changer, ou couper
  l'upscale, pour cette prise seulement ; **réinitialiser aux paramètres de la branche** y revient.
- **Retiré : l'upscale par clip** (⚙ de la colonne) : il ne reste que les LoRA du clip. Le choix « avec /
  sans » et les réglages propres donnés à un clip en 0.27 sont ignorés.
- **Fenêtre de plan ≡ : bloc Génération** : modèles, LoRA, réglages d'upscale et leur origine, graine,
  taille, taille des images de référence et chanson — ceux d'une prise ou d'une génération en cours, ou
  ceux qui seraient utilisés en lançant maintenant (emplacement vide, en-tête de colonne).
- **Corrigé** : « nullnullnull » écrit dans la fenêtre « prise réglée » (et dans quelques autres fenêtres).

## 0.27

- **≡ (plan) aussi sur les cases « générer » et « à la suite »** (le plan actuel du clip, pour relire le
  prompt avant de lancer) **et sur une génération en file ou en cours** (le plan avec lequel elle a été
  lancée, comparé au plan actuel).
- **Réglages d'upscale d'un clip et d'une prise** : les réglages du clip (⚙ de la colonne) peuvent avoir
  leurs propres réglages d'upscale (modèle, taille de départ, passes…), utilisés pour ce clip dans toutes
  les branches ; le dialogue « prise réglée » (▾) peut donner des réglages pour une seule prise, gardés par
  la prise (« ⟲ refaire » et ▾ repartent d'eux). La fenêtre de plan d'une prise dit avec quels réglages
  elle a été faite.
- **▶▶ « compléter »** : un libellé fixe (il ne déborde plus de l'en-tête de branche) ; ce qu'il fera est
  dans son infobulle.
- **Contrôle de version** : quand la page et le serveur qui tourne n'ont pas la même version (Encore mis à
  jour pendant qu'il tournait), un bandeau demande de relancer Encore.
- Derniers textes français traduits (point de sauvegarde avant un import, erreurs de niveaux de bruit de
  l'upscale, champ de graine).

## 0.26

- **Sources dans le dépôt** : les sources de l'interface sont dans `ui/` (`python ui/build.py` produit
  `web/index.html`), les tests dans `tests/` (`python tests/run_tests.py`, voir `tests/README.md`), avec un
  faux ComfyUI qui exécute le vrai code du plugin.
- **Nouveau test** : la validité des prises, calculée à la fois par le serveur et par la page, doit donner le
  même résultat (et les mêmes empreintes) sur une série de cas.
- **Retiré** : le code de l'appli que servait le plugin jusqu'à sa version 3.6 (elle n'existe plus), et celui
  du mode encore plus ancien « ouvrir le dossier du projet » de l'onglet Prises. Rien ne change à l'usage.
- **Correction** : modifier la « detailed_description » d'un clip de suite dont la phrase d'ouverture était
  écrite sans la phrase sur le son (mode libre, plans plus anciens ou écrits par un LLM) réécrivait cette
  phrase, ce qui invalidait les prises du clip. Une modification ordinaire garde désormais la phrase telle
  quelle ; seul « mettre la bonne phrase » la remplace.

## 0.25

- **Sécurité** : Encore refuse les requêtes venant d'autres pages web (un autre site, ou un site dont le nom
  désigne votre PC) ; `--host 0.0.0.0` pour l'ouvrir depuis un autre appareil du réseau.
- **ComfyUI redémarré ou injoignable** : les jobs qu'il a perdus reviennent dans la file d'Encore et sont
  renvoyés (deux fois au plus) ; images, voix et prises sont renvoyées aussi, de même après un changement
  d'adresse de ComfyUI. Avec l'interface en anglais, un ComfyUI injoignable à l'envoi faisait échouer le
  job : il attend désormais.
- **Onglet Prises** : sur une prise invalidée, « ⚠ ▶ assembler » passe en bas à gauche de l'image (il
  cachait « ⟲ refaire ») ; ▶▶ affiche bien « generating… » en anglais ; l'onglet fonctionne quand
  Encore est ouvert par son adresse réseau.
- **Assembler des prises invalidées** fonctionne après le renommage d'une référence.
- Derniers textes français traduits (décimales des fiches, messages Hugging Face, scripts d'installation).
  Dans `.infos.json`, `branche` devient `branch` (les anciennes fiches restent lues) et `video.clips` est
  un nombre.

## 0.24

- **Plan d'un clip** (≡ dans l'en-tête de colonne) et **plan d'une prise** (≡ sur une prise) : le plan avec
  lequel la prise a été faite, comparé au plan actuel (champs, prompt mot à mot, images de référence, passage
  de la chanson). Les prises enregistrent désormais leur plan ; pour les anciennes, Encore le cherche dans
  les plans qu'il conserve.
- **Replier une branche** (▾ / ▸) : un bandeau fin avec nom, nombre de prises et ▶▶ ; mémorisé par projet.
- **Assembler des prises invalidées** : « ⚠ ▶ assembler 1–k » assemble les prises réellement faites, après
  confirmation ; refusé si les tailles d'image diffèrent ; la fiche infos les liste.

## 0.23

- **ComfyUI partagé avec d'autres travaux** : Encore affiche les travaux qui passent avant les siens dans
  ComfyUI et donne ses estimations comme des minimums ; « pause immédiate » et « annuler » n'interrompent
  que le travail d'Encore.

## 0.22

- **Thème clair** (☀/☾ dans la barre du haut, ou Réglages par défaut › Thème).

## 0.21

- **Langues** : anglais par défaut, français ; un fichier par langue dans `encore/locales` (ajoutez la
  vôtre). La langue se choisit dans les Réglages par défaut.

## 0.20

- **Refonte de l'onglet Plan** : sujets (@noms avec autocomplétion, glisser-déposer), lignes de
  retention, résumé, un bloc par plan avec sa phrase d'ouverture automatique, « ↺ depuis le clip
  précédent » ; un nouveau clip reprend sujets, retention, style, ambiance sonore et références ;
  vignettes des références, voix et passage de la chanson du clip à l'écoute ; réglages du plan dans
  « ⚙ Réglages du plan ».
- **Onglet Prises** : le dialogue ▾ d'une prise part de son LoRA et de son upscale ; chaque liste de 8 choix
  ou plus a un champ de filtre.

## 0.19

- ▶▶ peut assembler la branche à la fin ; « ▶ assembler 1–k » sur une prise en file planifie l'assemblage.
- **Lots** : ce qu'un ▶▶ lance se déplace, se suspend et s'annule d'un bloc ; un échec n'arrête que ce qui en
  dépend.

## 0.18

- Case « + clip k à la suite » après chaque prise, ↻ (une autre prise depuis la même prise précédente), ▶▶
  (combler tous les trous d'une branche), dialogue « prise réglée » (LoRA, upscale, graine), ⟲ refaire avec
  la même graine.

## 0.17

- **Renommé Encore**, avec son icône. Écran d'accueil au premier lancement : dossier et Python de ComfyUI,
  paquets de nœuds obligatoires installés par `git clone` (optionnels à la demande), modèles par défaut
  téléchargés (espace disque vérifié), indicateur de connexion à ComfyUI. Scripts d'installation Linux
  (0.17.x).

## 0.6 à 0.16 (H3 Studio)

- Serveur local et interface navigateur qui pilotent ComfyUI par son API ; projets dans leur propre dossier
  (plan et ressources copiés dedans) ; points de sauvegarde de l'état complet du projet ; prises conservées
  et invalidées (jamais supprimées) quand ce qui les a produites change.
- Branches de prises, chacune avec ses références, sa taille d'image et sa chanson ; piles de LoRA (projet,
  branche, clip, prise) ; upscale latent ; aperçu en direct pendant la génération (celui de ComfyUI ou de
  KJNodes) ; file avec estimations, pause et réordonnancement ; vidéos assemblées avec leur fiche infos.
