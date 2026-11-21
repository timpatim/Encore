# Historique des versions

Versions d'Encore (appelé H3 Studio jusqu'à la 0.16). Chaque version est livrée sous la forme
`Encore_vX.Y.zip`. Encore a besoin du plugin ComfyUI
[ComfyUI-H3-ClipPlan](https://github.com/timpatim/ComfyUI-H3-ClipPlan) 3.6 ou plus récent.

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
