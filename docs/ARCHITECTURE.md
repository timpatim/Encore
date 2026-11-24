# Architecture d'Encore

Ce document dit quel fichier fait quoi, où intervenir pour une évolution, et quels tests lancer quand on
touche un fichier. Il est à tenir à jour quand un fichier change de rôle.

Encore est un serveur Python (bibliothèque standard seulement) et une page web d'un seul fichier. Il
pilote ComfyUI, où tournent les nœuds du plugin **ComfyUI-H3-ClipPlan** (dépôt séparé).

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
ComfyUI + plugin ComfyUI-H3-ClipPlan (plan, clip, sauvegarde du latent, assemblage de secours)
```

Parcours d'une génération :

1. **La page** appelle `POST …/generate` ; `server.py` passe la main à `Engine.generate`.
2. **`engine.py`** (section *launching*, `_generate`) compose le plan de la brindille (portions figées des
   prises précédentes + clips à venir, `plans.py`), vérifie les références, tire la graine, calcule l'upscale,
   enregistre la suite du plan de la future prise et met un job dans la file.
3. **`engine.py`** (section *sending a job to ComfyUI*) envoie le plan, les fichiers de référence et la chaîne
   de prises continuées (fiches réécrites par `takeplan.rewritten_record`), construit le workflow (`workflows.py`) et le met dans la file de ComfyUI.
4. **`engine.py`** (section *following the generations*) suit la progression par le websocket, puis
   récupère la nouvelle prise dans le projet (`takes.py`).

Parcours d'un assemblage :

1. **`engine.py`** (section *assemblies*) prend la brindille choisie (chaîne de prédécesseurs) et crée le job.
2. **Si possible, Encore assemble lui-même** avec ffmpeg (`assembler.py`) à partir des aperçus des prises.
   Sinon, le workflow d'assemblage part au plugin (`workflows.assemble_workflow`).
3. **La vidéo et ses fiches d'information** sont écrites dans `exports/` (`exports.py`).

## Serveur (`encore/`)

| Fichier | Rôle |
|---|---|
| `server.py` | Serveur web et API JSON : routes, configuration (`config.json`), surveillance de ComfyUI (`ComfyWatch`). Ne contient pas de logique métier : il appelle les autres modules. |
| `engine.py` | Le moteur : file d'attente des générations et assemblages, envoi à ComfyUI, suivi, récupération des prises. Seul fichier avec un état en mémoire et des threads (détail plus bas). |
| `workflows.py` | Fonctions pures : workflows ComfyUI (format API) d'un clip et d'un assemblage ; upscale latent en deux passes ; ce qu'un clip demande au projet (`clip_needs`) ; nœuds ComfyUI manquants. |
| `exports.py` | Fonctions pures : nom d'une nouvelle vidéo assemblée, fiches `.infos.json` / `.infos.md` (le ≡ d'une vidéo), liste des vidéos du volet latéral. |
| `diagnostic.py` | Journal de diagnostic des aperçus (`"diagnostic_preview": true` dans config.json). |
| `assembler.py` | Assemblage de la vidéo finale par Encore avec ffmpeg, à partir des aperçus des prises. |
| `plan_core.py` | Lecture, validation et minutage du plan. **Doit rester identique à `core.py` du plugin.** |
| `projects.py` | Projets sur disque : dossier, `project.json`, essence du projet (mode, vidéo, chanson, contexte : `set_essence`, `fit_essence`), branches (création vide / depuis un fichier / par duplication : `new_branch` ; clips repris `base` ; réglages figés, références utilisées), suppression, import de plan, `STUDIO_VERSION`. |
| `trash.py` | Supprimer une prise (avec les prises faites après elle) ou une branche (sans les prises reprises par une autre) ; la corbeille `trash/` : lister, restaurer, effacer. |
| `plans.py` | `plans.json` : plan maître de chaque branche, suite de plan de chaque prise ; composition du plan d'une brindille (`plan_of`, qui suit la sélection aux coupes ✂ et les clips repris d'une branche dupliquée), prises ✂ compatibles (`cut_fits`, `fits_map`), portion figée d'une prise, en-tête figé (`frozen_problems`). |
| `takes.py` | Prises d'un projet : fichiers, prédécesseur de chaque prise, sélection (une brindille). |
| `takeplan.py` | Le ≡ d'une prise ou d'un job (portion figée, consigne, génération) ; fiche réécrite envoyée au plugin. |
| `resources.py` | Suppression d'un fichier importé (image, voix, chanson, vidéo). |
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
| *"tout générer" for a branch* | `generate`, `fill_twig`, `job_plan`, `_pending_takes` | Lancer une prise ; ▶▶ « compléter » une brindille ; le ≡ d'un job |
| *assemblies* | `assemble`, `_assemble_twig`, `_make_assembly`, `active_in_branch`, `active` | Créer un job d'assemblage d'une brindille |
| *launching* | `_generate` | Créer un job de génération : plan de la brindille, références, graine, upscale, suite du plan |
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
| `plan_core.js` | Logique du plan, portage JS de `plan_core.py` (parité vérifiée par `tests/unit/parity_test.py`). |
| `plan_ui.js` | Écran de plan (plan maître ou plan d'une sélection) : liste des clips, clips figés 🔒, éditeur de clip, frise. |
| `plan_sections.js` | Éditeur « Sections » d'un prompt (sujets `@nom`). |
| `plan_takes_ui.js` | Écran principal des prises : branches, graphe des brindilles, barre de sélection, file, vidéos assemblées. |
| `plan_launch.js` | Panneau de lancement « ↻ nouvelle prise » / « + clip suivant » : brindille de départ, graine, réglages, éditeur du clip. |
| `plan_trash.js` | 🗑 d'une prise (confirmation qui liste ce qui part avec) et fenêtre Corbeille. |
| `plan_branch.js` | Fenêtres « Nouvelle branche » (vide, fichier, duplication) et « Réglages de la branche » ; bloc « Le projet » des réglages du projet. Ce qui est figé y est grisé avec sa raison. |
| `plan_studio.js` | Projets, imports, références, réglages, ouverture/fermeture de l'écran de plan (actif quand la page est servie par Encore). |
| `plan_dialog.js`, `plan_pick.js`, `plan_i18n.js` | Fenêtres de dialogue, listes filtrables, traductions. |
| `build.py` | Assemble la page. |

## Où intervenir

| Je veux changer… | Fichiers |
|---|---|
| Le workflow envoyé à ComfyUI (nœuds, échantillonneur, LoRA, aperçu) | `workflows.py` |
| L'upscale latent | `workflows.py` (`upscale_plan`, `add_upscale`) ; réglages : `projects.py`, `plan_takes_ui.js` |
| Ce qu'une génération envoie (plan, références, prises continuées) | `engine.py`, sections *launching* et *sending a job to ComfyUI* |
| La file d'attente (ordre, groupes, pause, estimations) | `engine.py`, sections *the Studio's queue* et *time estimates* ; affichage : `plan_takes_ui.js` |
| Le choix des prises d'un assemblage | `engine.py`, section *assemblies* ; `takes.select_chain` |
| Le plan maître, les suites de plan, ce qui est figé | `plans.py` ; écran : `plan_ui.js`, `plan_studio.js` |
| Le panneau de lancement d'une prise | `plan_launch.js`, `plan_takes_ui.js` (`openLaunch`) |
| Supprimer, la corbeille | `trash.py`, `plan_trash.js` |
| « Utiliser ce plan… » ; sélectionner une génération en cours | `projects.use_twig_plan`, `trash.replace_master` ; `plans.PENDING` ; `plan_studio.js` (`useThisPlan`), `plan_takes_ui.js` (`twigResolve`, `ghostCard`) |
| Créer, dupliquer, régler une branche ; l'essence du projet | `plan_branch.js` ; `projects.py` (`new_branch`, `set_essence`) |
| Les prises ✂ qui suivent la sélection | `plans.py` (`cut_fits`, `fits_map`, `chain`), `takes.py` (`follows`), `plan_takes_ui.js` (`linkOk`, `effPred`) |
| Le montage de la vidéo finale | `assembler.py` (ffmpeg) ; secours plugin : `workflows.assemble_workflow` |
| Les fiches ≡ des vidéos assemblées, leur nom, leur liste | `exports.py` |
| Le minutage, la validation du plan | `plan_core.py` **et** `plan_core.js`, **et** `core.py` du plugin |
| Une route de l'API | `server.py` |

## Tests

```
python3 tests/run_tests.py                                   # unitaires
CHROME=… H3_PLUGIN=… python3 tests/run_tests.py --e2e        # + bout en bout (~10 min)
CHROME=… H3_PLUGIN=… python3 tests/run_tests.py --e2e v30    # seulement les tests dont le nom contient « v30 »
```

Les tests de bout en bout démarrent le vrai serveur, un faux ComfyUI qui exécute le vrai code du plugin, et un
navigateur. Ils traversent donc presque tous `server.py`, `engine.py`, `projects.py`, `takes.py` et l'interface.
Certains réutilisent le projet du test précédent : pour en lancer un seul, lancer aussi ceux dont il dépend
(ordre dans `run_tests.py`). **La suite complète reste obligatoire avant chaque livraison.**

Tests à lancer en priorité quand on touche un fichier :

| Fichier | Tests |
|---|---|
| `workflows.py` | `upscale_test`, `v28`, `v30`, `v37`, `v38` |
| `exports.py` | `leaf_test`, `infos_test`, `v40` |
| `assembler.py` | `v40`, `v30`, `v37`, `v38` |
| `engine.py` — file, estimations | `queue_ui_test`, `v23`, `v25`, `v25_ui`, `v28` |
| `projects.py` (branches, essence) | `a2_api_test`, `a2_ui_test`, `v30`, `v37` |
| `engine.py` — génération, envoi, suivi | `a1_api_test`, `a2_api_test`, `v20`, `v20b`, `v25`, `v30`, `v34`, `v37`, `v38` |
| `engine.py` — assemblages | `a1_api_test`, `leaf_test`, `infos_test`, `v30`, `v40` |
| `takeplan.py` | `a1_api_test`, `v28` |
| `plans.py` | `a1_api_test`, `a1_ui_test`, `a2_api_test`, `cuts_test` (unitaire), `v31` |
| `takes.py`, `plan_core.py`, `plan_core.js` | `parity_test` (unitaire), `a1_api_test`, `v30`, `v37`, `v38` |
| `resources.py` | `v31` |
| `previews.py` | `v34`, `v36` |
| `comfy.py` | `v23`, `v25`, `v34` |
| `i18n.py`, `locales/` | `v21`, `v21b` |
| `theme.py` | `v22` |
| `plan_sections.js` | `sections_test`, `roundtrip_test` (unitaires), `v20` |
| `plan_ui.js` | `a1_ui_test`, `v20`, `v20b`, `v28`, `v30`, `v37`, `v38` |
| `plan_branch.js` | `a2_ui_test`, `v21b` |
| `trash.py`, `plan_trash.js` | `a3_api_test`, `a3_ui_test`, `a2_api_test` |
| `plan_takes_ui.js`, `plan_launch.js` | `a1_ui_test`, `a2_ui_test`, `v25_ui`, `v28`, `v29`, `v35`, `v36`, `queue_ui_test` |
| `plan_studio.js` | `v20`, `v30`, `v31`, `v34`, `v37` |

Aucun test ne couvre `diagnostic.py`, `comfy_setup.py`, `downloads.py` ni `folders.py` (en dehors du
démarrage de la page) : les vérifier à la main après une modification.
