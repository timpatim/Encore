# Historique des versions

Versions d'Encore (appelé H3 Studio jusqu'à la 0.16). Chaque version est livrée sous la forme
`Encore_vX.Y.zip`. Encore a besoin du plugin ComfyUI
[ComfyUI-H3-ClipPlan](https://github.com/timpatim/ComfyUI-H3-ClipPlan) 3.11 ou plus récent.

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
