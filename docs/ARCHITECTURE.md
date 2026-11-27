# Architecture d'Encore

Ce document dit quel fichier fait quoi, où intervenir pour une évolution, et quels tests lancer quand on
touche un fichier. Il est à tenir à jour quand un fichier change de rôle.

Encore est un serveur Python (bibliothèque standard seulement) et une page web d'un seul fichier. C'est un
front-end de composition : **toute l'inférence est faite par ComfyUI**. Encore compose le prompt, prépare les
fichiers (ffmpeg) et envoie à ComfyUI des workflows faits de ses nœuds natifs et de ceux de
ComfyUI-H3-Motion-Context-MultiRef et VideoHelperSuite. Depuis la 0.50, il n'utilise plus le plugin
ComfyUI-H3-ClipPlan ; le format de plan est le sien (`docs/PLAN_SPEC.md`, `docs/plan.schema.json`,
`docs/LLM_SYSTEM_PROMPT.md`).

## Vue d'ensemble

```
navigateur (web/index.html, construit depuis ui/)
    │  API JSON sur 127.0.0.1
    ▼
encore/server.py ── projects, plans, takes, resources, previews…   (fichiers du projet sur disque)
    │
    ▼
encore/engine.py ── workflows, exports, diagnostic, assembler, takeplan  (générations et assemblages)
    │  HTTP + websocket (encore/comfy.py)
    ▼
ComfyUI : nœuds natifs (MiniMax H3 Reference to Video, Load Image/Audio, sampler, décodages)
          + MultiRef (latent enregistré/chargé, contextes) + VHS (vidéos)
```

Parcours d'une génération :

1. **La page** appelle `POST …/generate` ; `server.py` passe la main à `Engine.generate`.
2. **`engine.py`** (section *launching*, `_generate`) compose le plan de la brindille (portions figées des
   prises précédentes + clips à venir, `plans.py`), vérifie les fichiers des clips, tire la graine, calcule l'upscale,
   enregistre la suite du plan de la future prise et met un job dans la file.
3. **`engine.py`** (section *sending a job to ComfyUI*, `_dispatch_clip`) compose le prompt H3
   (`plan_core.resolve_prompt`), prépare les fichiers avec ffmpeg (`prepare.py` : voix coupées, chanson décalée,
   morceau de vidéo), les envoie avec le latent de la prise continuée, construit le workflow (`workflows.py`,
   noms des entrées lus dans `/object_info` par `ref_inputs`) et le met dans la file de ComfyUI.
4. **`engine.py`** (section *following the generations*) suit la progression par le websocket, puis
   récupère la nouvelle prise dans le projet (`_harvest` : latent `.safetensors` et aperçu par `/view`, fiche
   écrite par Encore ; `takes.py`).

Parcours d'un assemblage :

1. **`engine.py`** (section *assemblies*) prend la brindille choisie (chaîne de prédécesseurs) et crée le job.
2. **Encore assemble lui-même** avec ffmpeg (`assembler.py`) à partir des aperçus des prises ; une prise sans
   aperçu n'est pas assemblée (il faut la refaire).
3. **La vidéo et ses fiches d'information** sont écrites dans `exports/` (`exports.py`).

## Serveur (`encore/`)

| Fichier | Rôle |
|---|---|
| `server.py` | Serveur web et API JSON : routes, configuration (`config.json`), surveillance de ComfyUI (`ComfyWatch`). Ne contient pas de logique métier : il appelle les autres modules. |
| `engine.py` | Le moteur : file d'attente des générations et assemblages, envoi à ComfyUI, suivi, récupération des prises. Seul fichier avec un état en mémoire et des threads (détail plus bas). |
| `workflows.py` | Fonctions pures : workflow ComfyUI (format API) d'un clip, avec les nœuds natifs, MultiRef et VHS (`clip_workflow` : latent préparé selon le cas, continuité, chanson, vidéo de départ ou éditée) ; noms des entrées multiples de `MiniMaxH3ReferenceToVideo` (`ref_inputs`) ; upscale latent en deux passes ; ce qu'un clip demande au projet (`clip_needs`) ; nœuds ComfyUI manquants. |
| `prepare.py` | Les fichiers qu'une génération envoie, préparés avec ffmpeg et gardés dans `cache/comfy/` du projet : voix coupées aux limites de H3, chanson décalée sur la frise du plan, morceau de vidéo (fin de la vidéo de départ, tranche d'un clip édité). |
| `latents.py` | Le fichier de latent d'une prise (`.safetensors` de MultiRef) ; conversion une fois des anciens `.pt` du plugin (lecture restreinte de l'archive torch, sans torch). |
| `exports.py` | Fonctions pures : nom d'une nouvelle vidéo assemblée, fiches `.infos.json` / `.infos.md` (le ≡ d'une vidéo), liste des vidéos du volet latéral. |
| `diagnostic.py` | Journal de diagnostic des aperçus (`"diagnostic_preview": true` dans config.json). |
| `assembler.py` | Assemblage de la vidéo finale par Encore avec ffmpeg, à partir des aperçus des prises. |
| `plan_core.py` | Lecture, validation et minutage du plan (version 7 : `files`, `subjects`) ; **composition du prompt H3** d'un clip (`compose_clip` : numéros des sujets, images et voix, définitions, rétention, ancres, préfixe de tâche, locuteurs `mark_speakers`) ; `snapshot_defs` (sujets et fichiers figés d'un clip généré), `preview` (le prompt composé pour la page). Depuis la 0.50, c'est le format d'Encore (il ne suit plus `core.py` du plugin). |
| `projects.py` | Projets sur disque : dossier, `project.json`, essence du projet (mode, vidéo, chanson, contexte : `set_essence`, `fit_essence`), branches (création vide / depuis un fichier / par duplication : `new_branch` ; clips repris `base` ; réglages figés), suppression d'une branche, suppression définitive d'un projet (`project_summary`, `delete_project`), import de plan, `video_file`, `STUDIO_VERSION`. |
| `trash.py` | Supprimer une prise (avec les prises faites après elle) ou une branche (sans les prises reprises par une autre) ; la corbeille `trash/` : lister, restaurer, effacer. |
| `plans.py` | `plans.json` : plan maître de chaque branche, suite de plan de chaque prise, ligne du plan maître (`line_of`) et plan maître figé (`frozen_of`, `freeze`, `master_frozen_problems`, qui laisse remplir un fichier sans chemin) ; composition du plan d'une brindille (`plan_of`, qui suit la sélection aux coupes ✂ et les clips repris d'une branche dupliquée ; 0.49 : portions reprises `kept_of`, clips laissés libres `holes_of`, `chain(branch=…)` qui fait suivre à un clip repris après un clip libre la prise de la branche), prises ✂ compatibles (`cut_fits`, `fits_map`), portion figée d'une prise, en-tête figé (`frozen_problems`). |
| `takes.py` | Prises d'un projet : fichiers, prédécesseur de chaque prise, sélection (une brindille). |
| `takeplan.py` | Le ≡ d'une prise ou d'un job (portion figée, consigne, génération). |
| `resources.py` | Fichiers importés (image, voix, chanson, vidéo) : état de chacun (`usages` : utilisé, seulement des prises, inutilisé), suppression d'un fichier, des inutilisés (`delete_unused`). |
| `previews.py` | Copies lisibles par le navigateur des vidéos importées (H.264). |
| `comfy.py` | Client HTTP et websocket de ComfyUI. |
| `comfy_setup.py` | Installation des nœuds dont ComfyUI a besoin (git clone + pip). |
| `downloads.py` | Téléchargement des modèles par défaut (Hugging Face). |
| `folders.py` | Navigateur de dossiers de la page. |
| `i18n.py`, `locales/` | Textes du serveur dans chaque langue (`en.json` est la référence). |
| `mdpage.py` | Affiche une fiche `.infos.md` en page HTML. |
| `theme.py` | Thème clair, dérivé du CSS sombre. |

### Le moteur, `engine.py`

Une seule classe, `Engine`, créée une fois par `server.py`. Ses méthodes sont rangées en sections, repérées
par des lignes `# ------ <titre>` :

| Section | Méthodes | Rôle |
|---|---|---|
| *helpers* | `client`, `_project`, `_comfy_down`, `_mirror`, `_ensure_socket`, `_object_info` | Accès à ComfyUI ; copie de travail côté ComfyUI (`_mirror`) |
| *persistence of the jobs* | `_jobs_file`, `_load`, `_save`, `_queue_file`, `_load_queue`, `_save_queue`, `_by_prompt` | `jobs.json` de chaque projet, `queue.json` |
| *the Studio's queue* | `_deps`, `_dependents`, `_group_root`, `_groups`, `_enqueue`, `queue_*`, `_requeue` | File d'Encore : groupes, dépendances, pause, déplacement, annulation |
| *public API* | `list_jobs`, `_public`, `preview`, `remove`, `cancel` | Ce que la page lit des jobs |
| *time estimates* | `_timings*`, `_record_timing`, `_median`, `_total_estimate`, `_count_foreign`, `_remaining`, `_estimates` | Durées restantes affichées dans la file |
| *"tout générer" for a branch* | `generate`, `fill_twig`, `job_plan`, `_pending_takes`, `files_waiting`, `project_busy`, `forget_project` | Lancer une prise ; ▶▶ « compléter » une brindille ; le ≡ d'un job |
| *assemblies* | `assemble`, `_assemble_twig`, `_make_assembly`, `active_in_branch`, `active` | Créer un job d'assemblage d'une brindille |
| *launching* | `_generate` | Créer un job de génération : plan de la brindille, portion figée avec ses `defs`, graine, upscale, suite du plan |
| *sending a job to ComfyUI* | `_dispatch_next`, `_dispatch_clip`, `_dispatch_assembly`, `_resolve_assembly`, `_ready`, `_sweep_orphans`, `_fail`, `_send_*`, `_put`, `_copy_into`, `_local_assemblies`, `_run_local_assembly`, `_write_export` | Choisir le prochain job ; envoyer plan, fichiers et prises continuées ; lancer les assemblages ffmpeg |
| *following the generations* | `_on_event`, `_on_binary`, `_poll_loop`, `_poll`, `_follow`, `_harvest`, `_harvest_assembly`, `_purge_*` | Progression, fin d'un job, récupération de la prise ou de la vidéo, ménage côté ComfyUI |

**État partagé** (créé dans `__init__`, protégé par `self.lock`, un `RLock`) : `jobs`, `order`, `paused`,
`loaded`, `mirror`, `mirror_url`, `comfy_down_at`, `uploaded`, `previews`, `local_procs`, `info`. Les
lancements (`generate`, `assemble`, `fill_twig`) passent aussi par `launch_lock`. Un thread
(`_poll_loop`) fait avancer la file ; le websocket appelle `_on_event` depuis son propre thread.

Les sections s'appellent beaucoup entre elles. Avant de modifier une méthode de persistance ou de file
(`_save`, `_fail`, `_requeue`, `_dependents`…), chercher ses appels dans tout le fichier : le suivi, l'envoi
et les assemblages en dépendent.

## Interface (`ui/` → `web/index.html`)

La page est un seul fichier, construit par `python3 ui/build.py` après chaque modification de `ui/*.js`,
**et après chaque changement de `STUDIO_VERSION`** : la page porte le numéro de version, et si elle ne
correspond pas à celui du serveur, un bandeau « versions différentes » s'affiche (et `v21b`, `v28` échouent).

| Fichier | Rôle |
|---|---|
| `editor_shell.html` | Squelette de la page et CSS (sombre ; le clair est dérivé par `theme.py`). |
| `plan_core.js` | Validation et minutage du plan, portage JS de `plan_core.py` (parité du minutage vérifiée par `tests/unit/parity_test.py`) ; sujets et fichiers d'un clip. La composition du prompt H3 reste côté serveur (`POST …/plan/compose`). |
| `plan_ui.js` | Écran de plan (plan maître ou plan d'une sélection) : liste des clips, clips figés 🔒, éditeur de clip, frise. |
| `plan_sections.js` | Éditeur d'un clip : onglets « Champs » (ancres, résumé, plans, son, musique, sujets du clip) et « Prompt H3 » (prompt composé, modifiable à la main) ; listes `@` et `/` (caméra) ; bibliothèque (sujets du plan, fichiers du projet, images à fournir) et fenêtre d'un sujet ; choix d'image (`pickImage`) et import par dépôt de fichiers de l'ordinateur (`dropFile`, `importDropped`). |
| `plan_takes_ui.js` | Écran principal des prises : branches (nom éditable, repliement), graphe des brindilles (arbre), barre de sélection, vue d'ensemble, ◎ génération en cours, vidéos assemblées. |
| `plan_launch.js` | Panneau de lancement « ↻ nouvelle prise » / « + clip suivant » : « Plan des clips suivants » (un choix par plan distinct, `drawTwigs`), graine, réglages, éditeur du clip. |
| `plan_trash.js` | 🗑 d'une prise (confirmation qui liste ce qui part avec) et fenêtre Corbeille. |
| `plan_branch.js` | Fenêtres « Nouvelle branche » (vide, fichier, duplication avec ses vignettes de portions par scène) et « Réglages de la branche » ; bloc « Le projet » des réglages du projet. Ce qui est figé y est grisé avec sa raison. |
| `plan_studio.js` | Barres du haut (application, projet, et ligne propre à l'écran de plan), projets (et leur suppression), imports, fenêtre Ressources, réglages, ouverture/fermeture de l'écran de plan (actif quand la page est servie par Encore). |
| `plan_dialog.js`, `plan_pick.js`, `plan_i18n.js` | Fenêtres de dialogue, listes filtrables, traductions. |
| `build.py` | Assemble la page. |

## Où intervenir

| Je veux changer… | Fichiers |
|---|---|
| Le workflow envoyé à ComfyUI (nœuds, échantillonneur, LoRA, aperçu) | `workflows.py` |
| L'upscale latent | `workflows.py` (`upscale_plan`, `add_upscale`) ; réglages : `projects.py`, `plan_takes_ui.js` |
| Ce qu'une génération envoie (prompt, fichiers préparés, prise continuée) | `engine.py`, sections *launching* et *sending a job to ComfyUI* ; `prepare.py` ; `workflows.clip_workflow` |
| Les nœuds et paquets qu'Encore demande ; l'écran d'installation | `data/node_packs.json`, `comfy_setup.py` (`status` : paquets, ffmpeg, ancien plugin) ; `plan_studio.js` |
| La file d'attente (ordre, groupes, pause, estimations) | `engine.py`, sections *the Studio's queue* et *time estimates* ; affichage : `plan_takes_ui.js` |
| Le choix des prises d'un assemblage | `engine.py`, section *assemblies* ; `takes.select_chain` |
| Le plan maître, les suites de plan, ce qui est figé | `plans.py` ; écran : `plan_ui.js`, `plan_studio.js` |
| La ligne du plan maître (cases, ▶▶) | `plans.line_of`, `engine._generate` (`line`), `engine.fill_twig` ; écran : `plan_takes_ui.js` (`buildBands`, `cellCard`, `fillButton`) |
| Le panneau de lancement d'une prise | `plan_launch.js`, `plan_takes_ui.js` (`openLaunch`) |
| Supprimer, la corbeille | `trash.py`, `plan_trash.js` |
| « Utiliser ce plan… » ; sélectionner une génération en cours | `projects.use_twig_plan`, `trash.replace_master` ; `plans.PENDING` ; `plan_studio.js` (`useThisPlan`), `plan_takes_ui.js` (`twigResolve`, `ghostCard`) |
| Créer, dupliquer, régler une branche ; l'essence du projet | `plan_branch.js` ; `projects.py` (`new_branch` avec `keep`, `portions_ok`, `set_essence`) |
| Les prises ✂ qui suivent la sélection | `plans.py` (`cut_fits`, `fits_map`, `chain`), `takes.py` (`follows`), `plan_takes_ui.js` (`linkOk`, `effPred`) |
| Le montage de la vidéo finale | `assembler.py` (ffmpeg) |
| Les fiches ≡ des vidéos assemblées, leur nom, leur liste | `exports.py` |
| Le minutage, la validation du plan | `plan_core.py` **et** `plan_core.js` ; docs : `docs/PLAN_SPEC.md`, `docs/plan.schema.json` |
| Le prompt H3 composé (formulations, numéros, locuteurs) | `plan_core.compose_clip`, `resolve_prompt` ; affichage : `plan_sections.js` |
| Les consignes pour faire écrire un plan par un LLM | `docs/LLM_SYSTEM_PROMPT.md` (et la compétence h3-clip-plan) |
| Les sujets, fichiers, ancres d'un clip à l'écran | `plan_sections.js` |
| Supprimer un projet ; les fichiers inutilisés | `projects.delete_project`, `engine.project_busy` ; `resources.py` ; `plan_studio.js` |
| Une route de l'API | `server.py` |

## Tests

```
python3 tests/run_tests.py                                   # unitaires
CHROME=… python3 tests/run_tests.py --e2e        # + bout en bout (~25 min)
CHROME=… python3 tests/run_tests.py --e2e v30    # seulement les tests dont le nom contient « v30 »
```

Les tests de bout en bout démarrent le vrai serveur, un faux ComfyUI (`tests/mock/mock_studio.py` : faux nœuds natifs, MultiRef et VHS qui vérifient ce qu'ils reçoivent et écrivent des fichiers de la bonne forme), et un
navigateur. Ils traversent donc presque tous `server.py`, `engine.py`, `projects.py`, `takes.py` et l'interface.
Certains réutilisent le projet du test précédent : pour en lancer un seul, lancer aussi ceux dont il dépend
(ordre dans `run_tests.py`). **La suite complète reste obligatoire avant chaque livraison.**

Tests à lancer en priorité quand on touche un fichier :

| Fichier | Tests |
|---|---|
| `workflows.py`, `prepare.py` | `upscale_test`, `b1_api_test`, `v28`, `v30`, `v37`, `v38` |
| `latents.py` | `latents_test` (unitaire), `a1_api_test` |
| `comfy_setup.py`, `data/node_packs.json` | `g1_setup_test`, `v21b`, `v25` |
| `exports.py` | `leaf_test`, `infos_test`, `v40` |
| `assembler.py` | `v40`, `v30`, `v37`, `v38` |
| `engine.py` — file, estimations | `queue_ui_test`, `v23`, `v25`, `v25_ui`, `v28` |
| `projects.py` (branches, essence, suppression) | `a2_api_test`, `a2_ui_test`, `b1_api_test`, `v30`, `v37` |
| `engine.py` — génération, envoi, suivi | `a1_api_test`, `a2_api_test`, `v20`, `v20b`, `v25`, `v30`, `v34`, `v37`, `v38` |
| `engine.py` — assemblages | `a1_api_test`, `leaf_test`, `infos_test`, `v30`, `v40` |
| `takeplan.py` | `a1_api_test`, `v28` |
| `plans.py` | `d1_api_test`, `a1_api_test`, `a1_ui_test`, `a2_api_test`, `cuts_test` (unitaire), `v31` |
| `takes.py`, `plan_core.py`, `plan_core.js` | `parity_test` (unitaire), `b1_api_test`, `a1_api_test`, `v30`, `v37`, `v38` |
| `resources.py` | `b1_api_test`, `v31` |
| `previews.py` | `v34`, `v36` |
| `comfy.py` | `v23`, `v25`, `v34` |
| `i18n.py`, `locales/` | `v21`, `v21b` |
| `theme.py` | `v22` |
| `plan_sections.js` | `sections_test` (unitaire), `b2_ui_test`, `e1_ui_test`, `v20` |
| `plan_branch.js` (dupliquer, portions) | `f1_ui_test`, `d2_ui_test`, `a2_ui_test` |
| `plan_ui.js` | `a1_ui_test`, `v20`, `v20b`, `v28`, `v30`, `v37`, `v38` |
| `plan_branch.js` | `a2_ui_test`, `v21b` |
| `trash.py`, `plan_trash.js` | `a3_api_test`, `a3_ui_test`, `a2_api_test` |
| `plan_takes_ui.js`, `plan_launch.js` | `d2_ui_test`, `c1_ui_test`, `a1_ui_test`, `a2_ui_test`, `v25_ui`, `v28`, `v29`, `v35`, `v36`, `queue_ui_test`, `e1_ui_test` |
| `plan_studio.js` | `b2_ui_test`, `c1_ui_test`, `v20`, `v30`, `v31`, `v34`, `v37` |

Aucun test ne couvre `diagnostic.py`, `comfy_setup.py`, `downloads.py` ni `folders.py` (en dehors du
démarrage de la page) : les vérifier à la main après une modification.
