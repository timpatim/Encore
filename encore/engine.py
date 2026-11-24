"""Encore - generations: the Studio decides, ComfyUI only computes.

For each generation the Studio
  1. sends ComfyUI what the existing ComfyUI-H3-ClipPlan nodes read: the plan, the reference
     files and, for a continuation, the take it continues (with the takes that one is built on);
  2. builds the workflow (Reference, Voice, Clip, sampler, SaveLatent, preview) and queues it;
  3. follows it (websocket for the progress, /queue and /history for the end);
  4. copies the new take (latent, signature, preview) into the project and chooses it.

ComfyUI's side is a working copy, under names of its own so that it never mixes with the plans
used directly in ComfyUI:
    input/h3studio/<project>/plan.json, reference files       (sent by the Studio)
    output/h3_clip_plan/h3studio_<project>/latents, clips      (takes being made or continued)
When no generation of the project is waiting any more, that working copy is emptied (configurable):
the takes are in the project, and leftovers must not interfere with the next generations.
"""
from __future__ import annotations

from .i18n import t as _t
import base64
import json
import os
import random
import threading
import time
import uuid
from pathlib import Path

from . import assembler, comfy, comfy_setup, plan_core, plans, projects, takeplan, takes
from .diagnostic import Diagnostic, image_size
from .exports import export_name, write_infos
from .projects import StudioError
from .workflows import (assemble_workflow, clip_needs, clip_workflow, kj_frames_value, latent_frames, missing_nodes,
                        upscale_plan)

MIRROR_PREFIX = "h3studio_"
INPUT_DIR = "h3studio"
STEP_KEYS = {"20": "engine.preparing", "25": "engine.generating", "26": "engine.saving", "27": "engine.decoding", "28": "engine.preview", "10": "engine.assembling"}
ACTIVE = ("queued", "running")


def mirror_name(project: str, branch: str) -> str:
    """ComfyUI's working copy of one branch (the plugin compares takes with each other: one set per copy)."""
    return f"{MIRROR_PREFIX}{project}__{branch}"


def plan_file_of(project: str, branch: str) -> str:
    return f"{INPUT_DIR}/{project}/{branch}/plan.json"


# --------------------------------------------------------------------------- engine
def _failed_dep(job):
    """Error message of a job that waited for `job`, which failed."""
    if job.get("kind") == "clip" and job.get("clip"):
        return _t("engine.clip_it_depends_on_has_failed", v0=job['clip'])
    return _t("engine.the_generation_it_depended_on_did")


def _ranges(numbers):
    """[3, 4, 5, 9] -> "3 à 5, 9" """
    runs = []
    for n in numbers:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return ", ".join(f"{a}" if a == b else _t("engine.to", a=a, b=b) for a, b in runs)


class Engine:
    def __init__(self, studio):
        self.studio = studio
        self.lock = threading.RLock()
        self.launch_lock = threading.RLock()
        self.client_id = "encore-" + uuid.uuid4().hex
        plans.PENDING = self._pending_takes      # a twig (the selection) can go through a take still being made
        self.jobs = {}              # job id -> job (job["prompt_id"]: its prompt in ComfyUI once dispatched)
        self.order = []             # ids of the jobs waiting in the Studio's own queue, in order (all projects)
        self.paused = False         # nothing new is sent to ComfyUI
        self.loaded = set()         # projects whose jobs.json was read
        self.mirror = {}            # (project, branch) -> {(clip, take id)} present in ComfyUI's working copy
        self.mirror_url = None      # the ComfyUI that mirror describes: another address starts from nothing
        self.comfy_down_at = None   # last time ComfyUI did not answer while jobs were running there
        self.uploaded = {}          # (comfy url, subfolder, name) -> sha already sent
        self.socket = None
        self.socket_url = None
        self.info = None
        self.info_time = 0
        self.previews = {}          # prompt id -> (image bytes, mime type)
        self.local_procs = {}       # job id -> ffmpeg process of an assembly made by Encore
        self.diagnostic = Diagnostic(Path(studio.config_path).resolve().parent) if studio.config.get("diagnostic_preview", False) else None
        self.wake = threading.Event()
        self._load_queue()
        self.poller = threading.Thread(target=self._poll_loop, daemon=True, name="encore-poll")
        self.poller.start()

    # ------------------------------------------------------------------ helpers
    @property
    def client(self):
        return comfy.ComfyClient(self.studio.config["comfy_url"])

    def _project(self, name):
        return projects.project_dir(self.studio.root, name)

    def _comfy_down(self):
        """ComfyUI does not answer: it may come back restarted, or reinstalled with empty folders. A job gone from
        its queue after this was lost by the restart, and what Encore sent it before is sent again."""
        with self.lock:
            self.comfy_down_at = time.time()
            self.uploaded.clear()
            self.mirror, self.mirror_url = {}, None

    def _mirror(self, name, branch):
        """The takes known to be in ComfyUI's copy of a branch; forgotten when the ComfyUI address changes."""
        url = self.studio.config.get("comfy_url")
        if url != self.mirror_url:
            self.mirror, self.mirror_url = {}, url
        return self.mirror.setdefault((name, branch), set())

    def _ensure_socket(self):
        url = self.studio.config["comfy_url"]
        if self.socket and self.socket_url == url and self.socket.is_alive():
            return
        if self.socket:
            self.socket.stop()
        self.socket = comfy.EventSocket(url, self.client_id, self._on_event, on_binary=self._on_binary)
        self.socket_url = url
        self.socket.start()

    def _object_info(self, force=False):
        if force or not self.info or time.time() - self.info_time > 60:
            self.info = self.client.object_info()
            self.info_time = time.time()
        return self.info

    # ------------------------------------------------------------------ persistence of the jobs
    def _jobs_file(self, name):
        return self._project(name) / "jobs.json"

    def _load(self, name):
        if name in self.loaded:
            return
        self.loaded.add(name)
        try:
            data = json.loads(self._jobs_file(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for job in data.get("jobs") or []:
            if job.get("id") and job["id"] not in self.jobs:
                job["progress"] = None
                if job.get("local") and job["status"] in ACTIVE:     # Encore closed during its own assembly
                    job.update(status="queued", local=None, step=None)
                if "dispatched" not in job:         # jobs of earlier versions: sent to ComfyUI at once
                    job["dispatched"], job["prompt_id"] = True, job["id"]
                self.jobs[job["id"]] = job
                if not job.get("dispatched") and job["status"] in ACTIVE and job["id"] not in self.order:
                    self.order.append(job["id"])
        if any(j["status"] in ACTIVE for j in self.jobs.values()):
            self._ensure_socket()
            self.wake.set()

    def _save(self, name):
        keep = [{k: v for k, v in j.items() if k != "progress"} for j in self.jobs.values()
                if j["project"] == name and j["status"] in ACTIVE + ("harvest",)]
        path = self._jobs_file(name)
        try:
            if keep:
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps({"jobs": keep}, indent=1, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, path)
            elif path.exists():
                path.unlink()
        except OSError:
            pass

    def _queue_file(self):
        return Path(self.studio.config_path).resolve().parent / "queue.json"

    def _load_queue(self):
        """The Studio's queue (all projects): order of the waiting jobs, pause."""
        try:
            data = json.loads(self._queue_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.paused = bool(data.get("paused"))
        wanted = [(p, i) for p, i in data.get("order") or []]
        for project in dict.fromkeys(p for p, _i in wanted):
            try:
                self._load(project)
            except Exception:  # noqa: BLE001 - a project that cannot be read
                continue
        known = [i for _p, i in wanted if i in self.jobs and not self.jobs[i].get("dispatched") and self.jobs[i]["status"] in ACTIVE]
        self.order = known + [i for i in self.order if i not in known]

    def _save_queue(self):
        data = {"paused": self.paused, "order": [[self.jobs[i]["project"], i] for i in self.order if i in self.jobs]}
        try:
            tmp = self._queue_file().with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, self._queue_file())
        except OSError:
            pass

    def _by_prompt(self, prompt_id):
        if not prompt_id:
            return None
        return next((j for j in self.jobs.values() if j.get("prompt_id") == prompt_id), None)

    # ------------------------------------------------------------------ the Studio's queue
    @staticmethod
    def _deps(job):
        """The jobs this one waits for: the generation it continues, and for a planned assembly every generation
        that makes one of its takes."""
        return [d for d in [job.get("parentJob")] + list(job.get("waitFor") or []) if d]

    def _dependents(self, job_id):
        """Jobs waiting for this one (and those waiting for them)."""
        out, todo = [], [job_id]
        while todo:
            current = todo.pop()
            for j in self.jobs.values():
                if current in self._deps(j) and j["status"] in ACTIVE and j["id"] not in out:
                    out.append(j["id"])
                    todo.append(j["id"])
        return out

    def _group_root(self, job):
        """First job of the group: going up the parents still waiting in the queue. A lot (what a ▶▶ launched, with
        its assembly) is one group whatever the links inside it."""
        if job.get("lot"):
            return "L" + job["lot"]
        seen = set()
        while job.get("parentJob") in self.order and job["parentJob"] not in seen:
            seen.add(job["parentJob"])
            job = self.jobs[job["parentJob"]]
        return job["id"]

    def _groups(self):
        """[(root id, [job ids in order])] for the waiting jobs."""
        groups, index = [], {}
        for jid in self.order:
            job = self.jobs.get(jid)
            if not job:
                continue
            root = self._group_root(job)
            if not job.get("lot"):
                top = job
                while top.get("parentJob") in self.jobs and not top.get("lot"):
                    top = self.jobs[top["parentJob"]]
                if top.get("lot") and top["id"] in self.order:
                    root = "L" + top["lot"]
            if root not in index:
                index[root] = len(groups)
                groups.append((root, []))
            groups[index[root]][1].append(jid)
        return groups

    def _enqueue(self, job):
        """A new job: after the last job of its group when it depends on a waiting one, else at the end."""
        parent = job.get("parentJob")
        if parent in self.jobs and self.jobs[parent].get("lot") and not job.get("lot") and parent in self.order:
            job["lot"], job["lot_label"] = self.jobs[parent]["lot"], self.jobs[parent].get("lot_label")
        if job.get("lot"):
            members = [i for i in self.order if self.jobs.get(i, {}).get("lot") == job["lot"]]
            if members and job.get("kind") == "assemble" and parent:
                # an assembly planned on a waiting generation of the lot: right after it, not after the whole lot
                at = self.order.index(parent) + 1 if parent in self.order else self.order.index(members[0])
                self.order.insert(at, job["id"])
                job["suspended"] = bool(self.jobs[members[0]].get("suspended"))
            elif members:
                self.order.insert(max(self.order.index(m) for m in members) + 1, job["id"])
                job["suspended"] = bool(self.jobs[members[0]].get("suspended"))
            else:
                self.order.append(job["id"])
            self._save_queue()
            return
        if parent in self.order:
            root = self._group_root(self.jobs[parent])
            members = dict(self._groups()).get(root, [])
            position = max(self.order.index(m) for m in members) + 1
            self.order.insert(position, job["id"])
            job["suspended"] = bool(self.jobs[parent].get("suspended"))
        else:
            self.order.append(job["id"])
        self._save_queue()

    def queue_state(self):
        """Everything the generation manager shows (all projects)."""
        with self.lock:
            now = time.time()
            estimates = self._estimates(now)
            branch_names = {}
            def describe(job):
                key = job["project"]
                if key not in branch_names:
                    try:
                        branch_names[key] = {b["id"]: (b["name"], b.get("color")) for b in projects.read_meta(self._project(key))["branches"]}
                    except Exception:  # noqa: BLE001
                        branch_names[key] = {}
                name, color = branch_names[key].get(job.get("branch"), (job.get("branch_name") or job.get("branch"), None))
                return dict(self._public(job), **estimates.get(job["id"], {}), project=job["project"], branch_name=name,
                            branch_color=color, dependents=len(self._dependents(job["id"])))
            sent = [describe(j) for j in sorted(self.jobs.values(), key=lambda j: j.get("dispatched_at", 0))
                    if j.get("dispatched") and j["status"] in ACTIVE + ("harvest",)]
            groups = [{"id": root, "suspended": all(self.jobs[i].get("suspended") for i in ids),
                       "label": next((self.jobs[i].get("lot_label") for i in ids if self.jobs[i].get("lot_label")), None),
                       "jobs": [describe(self.jobs[i]) for i in ids]} for root, ids in self._groups()]
            errors = [{"id": j["id"], "project": j["project"], "clip": j.get("clip"), "kind": j["kind"], "error": j.get("error")}
                      for j in self.jobs.values() if j["status"] == "error"]
        return {"paused": self.paused, "comfy_foreign": getattr(self, "comfy_foreign", 0), "sent": sent, "groups": groups, "waiting": sum(len(g["jobs"]) for g in groups), "errors": errors,
                "socket": bool(self.socket and self.socket.connected)}

    def queue_pause(self, mode):
        """mode "after": the job running ends, nothing else starts; "now": it is interrupted and goes back to the
        head of the queue (it will start again from the beginning, same seed)."""
        with self.lock:
            self.paused = True
            self._save_queue()
            sent = [j for j in self.jobs.values() if j.get("dispatched") and j["status"] in ACTIVE] if mode == "now" else []
        if sent:
            client = self.client
            try:
                state = client.queue_state()
                running = {row[1] for row in state.get("queue_running") or []}
                waiting = [j["prompt_id"] for j in sent if j["prompt_id"] not in running]
                if waiting:
                    client.delete_queued(waiting)
                for job in sent:
                    if job["prompt_id"] in running:
                        job["requeue"] = True
                        client.interrupt(job["prompt_id"])
                    else:
                        self._requeue(job)
            except comfy.ComfyError as exc:
                raise StudioError(str(exc)) from exc
        self.wake.set()
        return self.queue_state()

    def queue_resume(self):
        with self.lock:
            self.paused = False
            self._save_queue()
        self.wake.set()
        return self.queue_state()

    def _requeue(self, job):
        """A job interrupted by a pause: back to the head of the queue, as it was when it was launched."""
        with self.lock:
            for key in ("prompt_id", "t_start", "t_sample", "t_step", "t_sample_end", "requeue", "missing", "dispatched_at"):
                job.pop(key, None)
            job.update(status="queued", dispatched=False, progress=None, step=None, error=None, preview=None)
            self.previews.pop(job["id"], None)
            if job["id"] not in self.order:
                self.order.insert(0, job["id"])
            self._save(job["project"])
            self._save_queue()

    def queue_move(self, group, before=None):
        """Moves a whole group before another one (None: at the end). The order inside a group never changes."""
        with self.lock:
            groups = self._groups()
            ids = dict(groups).get(group)
            if not ids:
                raise StudioError(_t("engine.this_group_is_no_longer_in"))
            rest = [(r, m) for r, m in groups if r != group]
            position = next((n for n, (r, _m) in enumerate(rest) if r == before), len(rest))
            rest.insert(position, (group, ids))
            self.order = [i for _r, members in rest for i in members]
            self._save_queue()
        self.wake.set()
        return self.queue_state()

    def queue_suspend(self, group, suspended):
        with self.lock:
            ids = dict(self._groups()).get(group)
            if not ids:
                raise StudioError(_t("engine.this_group_is_no_longer_in"))
            for jid in ids:
                self.jobs[jid]["suspended"] = bool(suspended)
            for name in {self.jobs[i]["project"] for i in ids}:
                self._save(name)
        self.wake.set()
        return self.queue_state()

    def queue_cancel(self, ids):
        """Cancels jobs of any project, and the jobs that depend on them."""
        with self.lock:
            names = {self.jobs[i]["project"] for i in ids if i in self.jobs}
        for name in names:
            self.cancel(name, [i for i in ids if i in self.jobs and self.jobs[i]["project"] == name])
        return self.queue_state()

    # ------------------------------------------------------------------ public API
    def list_jobs(self, name):
        with self.lock:
            self._load(name)
            now = time.time()
            for jid in [j for j, job in self.jobs.items() if job["status"] == "done" and now - job.get("ended", now) > 60]:
                del self.jobs[jid]
            estimates = self._estimates(now)
            jobs = [dict(self._public(j), **estimates.get(j["id"], {})) for j in self.jobs.values() if j["project"] == name]
        jobs.sort(key=lambda j: j["created"])
        return {"jobs": jobs, "socket": bool(self.socket and self.socket.connected), "paused": self.paused}

    # ------------------------------------------------------------------ time estimates
    # Durations of past generations, per unit of work (pixels x frames), kept next to config.json:
    #   prep  seconds before sampling starts (models, encoding)      - not scaled
    #   step  seconds per sampling step and per unit
    #   post  seconds after sampling (decoding, preview, copy) per unit
    #   unit  seconds per unit for an assembly
    def _timings_path(self):
        return Path(self.studio.config_path).resolve().parent / "timings.json"

    def _timings(self):
        if getattr(self, "_timings_cache", None) is None:
            try:
                self._timings_cache = json.loads(self._timings_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._timings_cache = {"clip": [], "assemble": []}
        return self._timings_cache

    def _record_timing(self, job):
        units, end = job.get("units"), job.get("ended") or time.time()
        if not units or not job.get("t_start"):
            return
        data = self._timings()
        if job.get("kind") == "assemble":
            entry = {"unit": (end - job["t_start"]) / units}
            data.setdefault("assemble", []).append(entry)
        elif job.get("upscale"):
            data.setdefault("clip_upscale", []).append({"unit": (end - job["t_start"]) / units})
        else:
            if not (job.get("t_sample") and job.get("t_sample_end") and job.get("steps")):
                return
            entry = {"prep": job["t_sample"] - job["t_start"],
                     "step": (job["t_sample_end"] - job["t_sample"]) / job["steps"] / units,
                     "post": (end - job["t_sample_end"]) / units}
            data.setdefault("clip", []).append(entry)
        for key in ("clip", "assemble", "clip_upscale"):
            data[key] = data.get(key, [])[-30:]
        try:
            self._timings_path().write_text(json.dumps(data, indent=0), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _median(values):
        values = sorted(v for v in values if v is not None and v >= 0)
        return values[len(values) // 2] if values else None

    def _total_estimate(self, job):
        """Expected duration of a whole job, from past ones (None if unknown)."""
        data, units = self._timings(), job.get("units")
        if not units:
            return None
        if job.get("kind") == "assemble" or job.get("upscale"):
            unit = self._median([e.get("unit") for e in data.get("assemble" if job.get("kind") == "assemble" else "clip_upscale", [])])
            return unit * units if unit is not None else None
        prep = self._median([e.get("prep") for e in data.get("clip", [])])
        step = self._median([e.get("step") for e in data.get("clip", [])])
        post = self._median([e.get("post") for e in data.get("clip", [])])
        if None in (prep, step, post):
            return None
        return prep + step * units * int(job.get("steps") or 0) + post * units

    def _count_foreign(self, state):
        """ComfyUI may run work of its own (or of another app): count what is ahead of each job sent by Encore."""
        mine = {j["prompt_id"] for j in self.jobs.values() if j.get("prompt_id")}
        rows = [(-1, r[1]) for r in state.get("queue_running") or []] + [(r[0], r[1]) for r in state.get("queue_pending") or []]
        foreign = [(n, pid) for n, pid in rows if pid not in mine]
        self.comfy_foreign = len(foreign)
        with self.lock:
            for job in self.jobs.values():
                if not job.get("dispatched") or job["status"] not in ACTIVE:
                    continue
                own = next((n for n, pid in rows if pid == job.get("prompt_id")), None)
                job["comfy_ahead"] = 0 if own is None or own == -1 else sum(1 for n, _pid in foreign if n < own)

    def _remaining(self, job, now):
        """Seconds left for a running job (None if unknown)."""
        data, units = self._timings(), job.get("units") or 0
        post = self._median([e.get("post") for e in data.get("clip", [])])
        if job.get("kind") == "assemble" or job.get("upscale"):
            total = self._total_estimate(job)
            return max(0.0, total - (now - job.get("t_start", now))) if total is not None else None
        if job.get("t_sample_end"):
            return max(0.0, post * units - (now - job["t_sample_end"])) if post is not None else None
        t_step = job.get("t_step")
        if t_step and job.get("t_sample") and t_step[0] > 0:
            value, top, at = t_step
            per_step = (at - job["t_sample"]) / value
            left = per_step * max(0, top - value) - (now - at)
            return max(0.0, left) + (post * units if post is not None else 0.0)
        total = self._total_estimate(job)
        if total is None:
            return None
        return max(0.0, total - (now - job.get("t_start", now)))

    def _estimates(self, now):
        """{job id: {"eta": seconds left} or {"start_in": seconds}} for the Studio's jobs, in queue order."""
        out, ahead = {}, 0.0
        sent = sorted((j for j in self.jobs.values() if j["status"] in ACTIVE and j.get("dispatched")),
                      key=lambda j: (j["status"] != "running", j.get("dispatched_at", 0)))
        waiting = [self.jobs[i] for i in self.order if i in self.jobs and not self.jobs[i].get("suspended")]
        active = sent + ([] if self.paused else waiting)
        known, lower = True, False
        for job in active:
            if job["status"] == "running":
                left = self._remaining(job, now)
                if left is None:
                    known = False
                else:
                    out[job["id"]] = {"eta": round(left)}
                    ahead += left
            else:
                if job.get("comfy_ahead"):
                    lower = True       # ComfyUI has other work before it: the estimates become a minimum
                if known:
                    out[job["id"]] = {"start_in": round(ahead)}
                    if lower:
                        out[job["id"]]["at_least"] = True
                total = self._total_estimate(job)
                if total is None:
                    known = False
                else:
                    ahead += total
        return out

    @staticmethod
    def _public(job):
        out = {k: job.get(k) for k in ("id", "kind", "clip", "token", "parentToken", "parentJob", "status", "progress", "step",
                                       "error", "take", "created", "seed", "preview", "previewMime", "branch",
                                       "clips", "export", "eta", "start_in", "takes", "upscale", "suspended", "take_id", "leaf",
                                       "frames", "loras", "lot", "waitFor", "comfy_ahead", "at_least")}
        out["dispatched"] = bool(job.get("dispatched"))
        out["predecessor"] = (job.get("studio") or {}).get("predecessor")
        if job.get("kind") == "clip" and job.get("take_id"):
            # the take this generation will make, as far as it is known: ↻ « new take » works before it is finished
            st = job.get("studio") or {}
            out["record"] = {"id": job["take_id"], "seed": job.get("seed"), "pending": True,
                             "studio": {k: st.get(k) for k in ("branch", "portion", "predecessor", "extra_loras", "upscale")
                                        if st.get(k) is not None}}
        if job.get("pending"):
            out["waiting_for"] = _t("engine.waiting_for_clips", count=len(job["pending"]), clips=_ranges(sorted(int(k) for k in job["pending"])))
        return out

    def preview(self, name, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["project"] != name:
                return None
            return self.previews.get(job_id)

    def remove(self, name, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job and job["project"] == name and job["status"] not in ACTIVE:
                del self.jobs[job_id]
                self._save(name)
        return self.list_jobs(name)

    def cancel(self, name, ids):
        """Take queued generations out of ComfyUI's queue, interrupt the running one."""
        with self.lock:
            wanted = [i for i in ids if i in self.jobs and self.jobs[i]["project"] == name]
            for i in list(wanted):                       # what depends on a cancelled job cannot run any more
                wanted += [d for d in self._dependents(i) if d not in wanted]
            targets = [self.jobs[i] for i in wanted]
        sent = [j for j in targets if j.get("dispatched") and j["status"] in ACTIVE]
        client = self.client
        if sent:
            try:
                state = client.queue_state()
                now_running = {row[1] for row in state.get("queue_running") or []}
                queued = [j["prompt_id"] for j in sent if j["prompt_id"] not in now_running]
                if queued:
                    client.delete_queued(queued)
                for j in sent:
                    if j["prompt_id"] in now_running:
                        client.interrupt(j["prompt_id"])
            except comfy.ComfyError as exc:
                raise StudioError(str(exc)) from exc
        for job in targets:
            proc = self.local_procs.get(job["id"])
            if proc is not None:
                try:
                    proc.kill()
                except OSError:
                    pass
        with self.lock:
            for job in targets:
                self.jobs.pop(job["id"], None)
                self.previews.pop(job["id"], None)
                if job["id"] in self.order:
                    self.order.remove(job["id"])
            self._save(name)
            self._save_queue()
        for job in targets:
            if job.get("kind") == "assemble" and job.get("dispatched"):
                self._purge_workspace(client, job)
        self.wake.set()
        return self.list_jobs(name)

    def generate(self, name, clip_index, after=None, plan_from=None, entry=None, seed=None, branch=None, loras=None,
                 upscale_settings=None, edit_instruction=None):
        """A new take of clip clip_index (chantier A).
        after: the take of the previous clip it follows (a take, or the take id of a generation still waiting);
        None for clip 1. plan_from: the leaf of the twig whose plan gives the clip (when entry is None) and the
        suite of the new take; by default the twig ending with `after` (« clip suivant »), or the master plan.
        entry: the clip as set in the launch panel. seed: None = random. loras / upscale_settings: None = the
        branch's. edit_instruction: None = that of the plan."""
        with self.launch_lock:
            return self._generate(name, int(clip_index), (after or "").strip() or None, (plan_from or "").strip() or None,
                                  entry, None if seed in (None, "") else int(seed), branch or None, loras,
                                  upscale_settings, edit_instruction)

    # ------------------------------------------------------------------ ▶▶ compléter: the rest of a twig's plan
    def fill_twig(self, name, branch_id, leaf=None, dry_run=True, assemble=True):
        """Generates the clips of a twig's plan that have no take yet (after its leaf; the whole master plan
        without a leaf), each one after the one before, with a random seed. dry_run: only says what would be
        generated."""
        with self.launch_lock:
            path = self._project(name)
            branch = projects.find_branch(projects.read_meta(path)["branches"], branch_id)
            with self.lock:
                self._load(name)
                busy = [j for j in self.jobs.values() if j["project"] == name and j["status"] in ACTIVE
                        and j.get("kind") != "assemble" and j.get("branch") == branch_id]
            if busy:
                raise StudioError(_t("engine.generation_s_of_this_branch_are", v0=len(busy)), code="busy")
            twig = plans.plan_of(path, branch_id, leaf or None, pending=self._pending_takes(name), project_name=name)
            plan_raw = twig["plan"]
            errors, _w = plan_core.validate(json.loads(json.dumps(plan_raw)))
            if errors:
                raise StudioError(_t("engine.the_plan_has_error_s", v0=len(errors), v1=errors[0]))
            plan = plan_core.normalize(json.loads(json.dumps(plan_raw)))
            settings = projects.read_project(self.studio.root, name)["settings"]
            steps = int(settings.get("steps") or 8)
            w, h = branch.get("width") or 960, branch.get("height") or 544
            items, total, known = [], 0.0, True
            for clip in plan["clips"][twig["locked"]:]:
                estimate = self._total_estimate({"units": int(w) * int(h) * int(clip["frames"]) / 1e6, "steps": steps,
                                                 "upscale": bool(projects.upscale_of(branch).get("enabled"))})
                if estimate is None:
                    known = False
                else:
                    total += estimate
                items.append({"clip": clip["index"], "name": clip.get("name") or "", "frames": clip["frames"],
                              "new_scene": not (clip["continue"] and clip["index"] > 1)})
            todo = {"branch": branch_id, "branch_name": branch["name"], "leaf": leaf, "items": items,
                    "eta": round(total) if items and known else None}
            if dry_run or not items:
                return todo
            lot = uuid.uuid4().hex[:10]
            label = _t("engine.fill_label", branch=branch["name"], s="s" if len(items) > 1 else "",
                       clips=_ranges([i["clip"] for i in items])) + (_t("engine.assembly") if assemble else "")
            # a duplicated branch without its own take yet: after the last clip it takes over
            launched, made, previous = [], {}, leaf or (twig["chain"][-1] if twig["chain"] else None)
            for item in items:
                job = self._generate(name, item["clip"], previous, previous, None, None, branch_id, None, None, None,
                                     lot=lot, lot_label=label)
                launched.append(job["id"])
                made[item["clip"]] = job["id"]
                previous = job["take_id"]
            assembly = None
            if assemble:
                assembly = self._assemble_twig(name, previous, lot=lot, lot_label=label)
            return dict(todo, launched=launched, assembly=assembly["id"] if assembly else None)

    def job_plan(self, name, job_id):
        """The plan a queued or running generation was launched with (the ≡ of its card)."""
        with self.lock:
            job = self.jobs.get(str(job_id))
        if not job or job.get("project") != name or job.get("kind") != "clip":
            raise StudioError(_t("engine.generation_not_found"))
        return takeplan.job_plan(self.studio.root, name, job)

    def _pending_takes(self, name):
        """{take id: (clip, pseudo-record)} of the generations still waiting: a twig can go through them."""
        with self.lock:
            self._load(name)
            return {j["take_id"]: (j["clip"], {"id": j["take_id"], "frames": j["frames"], "studio": j.get("studio") or {},
                                               "seed": j.get("seed"), "job": j["id"]})
                    for j in self.jobs.values() if j["project"] == name and j.get("kind") == "clip"
                    and j.get("take_id") and j["status"] in ACTIVE + ("harvest",)}

    # ------------------------------------------------------------------ assemblies (from a take, a twig or the queue)
    def assemble(self, name, clip=None, take_id=None, job_id=None):
        """Assembles the twig ending with take_id (or with the take a waiting generation will make)."""
        with self.launch_lock:
            if job_id:
                with self.lock:
                    self._load(name)
                    job = self.jobs.get(str(job_id))
                if not job or job["project"] != name or job["kind"] != "clip" or job["status"] not in ACTIVE:
                    raise StudioError(_t("engine.this_generation_is_no_longer_waiting"))
                return self._assemble_twig(name, job["take_id"], lot=job.get("lot"), lot_label=job.get("lot_label"))
            return self._assemble_twig(name, str(take_id or ""))

    def _assemble_twig(self, name, leaf_id, lot=None, lot_label=None):
        """The assembly of the clips 1..k of a twig. Takes still to come (generations waiting) are given when they
        are harvested. The plan sent is the plan of the twig as its takes were made."""
        path = self._project(name)
        project = projects.read_project(self.studio.root, name)
        pending = self._pending_takes(name)
        known = plans.records_by_id(path)
        if leaf_id not in known and leaf_id not in pending:
            raise StudioError(_t("engine.take_no_longer_exists", leaf_id=leaf_id))
        leaf_record = known[leaf_id][1] if leaf_id in known else pending[leaf_id][1]
        branch_id = takes.take_branch(leaf_record, None)
        branch = projects.find_branch(project["branches"], branch_id)
        twig = plans.plan_of(path, branch_id, leaf_id, known, pending, project_name=name)
        count = twig["locked"]
        raw = dict(twig["plan"], clips=twig["plan"]["clips"][:count])
        plan = plan_core.normalize(json.loads(json.dumps(raw)))
        chosen = {i: t for i, t in twig["takes"].items() if t in known}
        waiting = {i: pending[t][1]["job"] for i, t in twig["takes"].items() if t not in known}
        return self._make_assembly(name, path, raw, plan, project["settings"], branch, chosen, count, leaf=leaf_id,
                                   pending=waiting, wait_for=list(waiting.values()), lot=lot, lot_label=lot_label)

    def _make_assembly(self, name, path, raw, plan, settings, branch, chosen, count, leaf=None, pending=None,
                       wait_for=None, lot=None, lot_label=None):
        """The assembly job of clips 1..count. chosen: {clip: take id} for takes that exist; pending: {clip: job id}
        for takes still to generate (resolved when they are harvested). raw: the plan of the twig."""
        branch_id = branch["id"]
        free = plan["mode"] == "free"
        workspace = f"{branch_id}_a{uuid.uuid4().hex[:8]}"
        with self.lock:
            self._load(name)
            waiting = {j.get("export") for j in self.jobs.values() if j["project"] == name and j.get("kind") == "assemble"
                       and j["status"] in ACTIVE + ("harvest",)}
        export = export_name(path, name, branch["name"], taken=waiting)
        try:
            info = self._object_info()
        except comfy.ComfyError as exc:
            raise StudioError(str(exc)) from exc
        start = plan.get("start_video") if (plan.get("start_video") or {}).get("in_assembly") else None
        edit = plan.get("edit_video") if (plan.get("edit_video") or {}).get("sound") == "original" else None
        missing = [n for n in ["VAELoader", "H3PlanAssemble"] + ([] if free else ["LoadAudio"])
                   + (["H3PlanVideo", "MiniMaxH3AudioVAECompatibility"] if start else [])
                   + (["H3PlanVideo"] if edit else []) if n not in info]
        if missing:
            raise StudioError(_t("engine.nodes_missing_from_comfyui") + ", ".join(missing)
                              + (_t("engine.video_node_needs_plugin") if "H3PlanVideo" in missing else ""))
        start_video = None
        if start:                                     # the segment opens the video: the project's start video
            rel = (projects.effective_refs(path, branch, plan).get(start["ref"]) or {}).get("video")
            video_file = projects.safe_join(path, rel or "")
            if not rel or not video_file.is_file():
                raise StudioError(_t("engine.start_video_not_chosen"))
            start_video = {"name": start["ref"], "video": rel, "sha": takes.file_sha(video_file)}
        edit_video = None
        if edit:                                      # the final video keeps the edited video's sound
            rel = (projects.effective_refs(path, branch, plan).get(edit["ref"]) or {}).get("video")
            video_file = projects.safe_join(path, rel or "")
            if not rel or not video_file.is_file():
                raise StudioError(_t("engine.edit_video_not_chosen"))
            edit_video = {"name": edit["ref"], "video": rel, "sha": takes.file_sha(video_file)}
        if not free and not projects.safe_join(path, branch.get("song") or "").is_file():
            raise StudioError(_t("engine.song_of_branch_not_found", v0=branch['name']))
        size = [branch.get("width"), branch.get("height")]
        job = {"id": "j" + uuid.uuid4().hex[:15], "prompt_id": None, "dispatched": False,
               "spec": {"raw": raw, "mode": plan["mode"], "settings": settings, "song": None if free else branch.get("song"),
                        "start_video": start_video, "edit_video": edit_video},
               "project": name, "branch": branch_id, "kind": "assemble", "clips": count,
               "frames": int(plan_core.timeline(plan)[count - 1]["end"]) - plan_core.final_start(plan),
               "workspace": workspace, "leaf": leaf,
               "takes": {str(k): v for k, v in chosen.items()}, "pending": {str(k): v for k, v in (pending or {}).items()},
               "parentJob": None, "waitFor": list(wait_for or []), "lot": lot, "lot_label": lot_label,
               "export": export, "status": "queued", "progress": None, "step": None,
               "error": None, "take": None, "created": time.time(), "clip": count + 1, "token": None, "parentToken": None,
               "seed": None, "branch_name": branch["name"], "size": size,
               "plan_snapshot": raw, "crf": int(settings.get("crf") or 0) or None,
               "ref_image_size": branch.get("ref_image_size"), "song_file": branch.get("song") if plan["mode"] != "free" else None,
               "units": int(size[0]) * int(size[1]) * int(plan_core.timeline(plan)[count - 1]["end"]) / 1e6}
        with self.lock:
            self.jobs[job["id"]] = job
            self._enqueue(job)
            self._save(name)
        self.wake.set()
        return self._public(job)

    def active_in_branch(self, name, branch, default):
        return [j for j in self.active(name) if (j.get("branch") or default) == branch]

    def active(self, name):
        with self.lock:
            self._load(name)
            return [j for j in self.jobs.values() if j["project"] == name and j["status"] in ACTIVE + ("harvest",)]

    # ------------------------------------------------------------------ launching
    def _generate(self, name, index, after, plan_from, entry, forced_seed, branch_id, take_loras, upscale_settings,
                  edit_instruction, lot=None, lot_label=None):
        path = self._project(name)
        project = projects.read_project(self.studio.root, name)
        settings, branches = project["settings"], project["branches"]
        if any(l.get("enabled") and not l.get("name") for l in settings.get("loras") or []):
            raise StudioError(_t("engine.an_active_lora_has_no_file"))
        known = plans.records_by_id(path)
        pending = self._pending_takes(name)

        # the take before this one (it continues it, or the new scene is timed after it)
        after_job = None
        if index == 1:
            after = None
        else:
            if not after:
                raise StudioError(_t("engine.clip_needs_the_take_before", index=index, v1=index - 1))
            if after in known:
                after_index, after_record = known[after]
            elif after in pending:
                after_index, after_record = pending[after]
                after_job = after_record["job"]
            else:
                raise StudioError(_t("engine.the_take_of_clip_this_clip", v0=index - 1))
            if after_index != index - 1:
                raise StudioError(_t("engine.the_take_of_clip_this_clip", v0=index - 1))
            # the branch of the take before, unless it is one the given branch takes over (duplicated with clips)
            if not branch_id or after not in plans.base_of(path, branch_id):
                branch_id = takes.take_branch(after_record, branch_id)
        if not branch_id:
            raise StudioError(_t("engine.no_branch_create_one_with_new"))
        branch = projects.find_branch(branches, branch_id)
        taken_over = projects.branch_base(branch)
        if index <= len(taken_over):
            raise StudioError(_t("engine.clip_taken_over", index=index, branch=branch["name"], k=len(taken_over)))

        # the plan: the twig before (portions), this clip, then the suite of the twig it is taken from
        source = plans.plan_of(path, branch_id, plan_from or after, known, pending, project_name=name)
        if plan_from and index > 1 and (len(source["chain"]) < index - 1 or source["chain"][index - 2] != after):
            raise StudioError(_t("engine.plan_from_not_through", v0=index - 1))
        src = source["plan"]
        if entry is None:
            if len(src["clips"]) < index:
                raise StudioError(_t("engine.the_plan_has_no_clip", index=index))
            entry = src["clips"][index - 1]
        if not isinstance(entry, dict):
            raise StudioError(_t("engine.the_plan_has_no_clip", index=index))
        entry = json.loads(json.dumps(entry))
        entry.pop("seed", None)
        before = plans.plan_of(path, branch_id, after, known, pending, project_name=name)["plan"] if after else {"clips": [], "refs": {}}
        composed = plans.head(src)
        if edit_instruction is not None and isinstance(composed.get("edit_video"), dict):
            composed["edit_video"]["instruction"] = str(edit_instruction)
        composed["refs"] = {**(before.get("refs") or {}), **(composed.get("refs") or {})}
        composed["clips"] = before["clips"][:index - 1] + [entry] + json.loads(json.dumps(src["clips"][index:]))
        composed["project"] = name
        composed.pop("seed", None)
        errors, _warnings = plan_core.validate(json.loads(json.dumps(composed)))
        if errors:
            raise StudioError(_t("engine.the_plan_has_error_s", v0=len(errors), v1=errors[0]))
        raw = composed
        plan = plan_core.normalize(json.loads(json.dumps(raw)))
        clip = plan["clips"][index - 1]
        free = plan["mode"] == "free"

        settings = dict(settings, width=int(branch.get("width") or 960), height=int(branch.get("height") or 544))
        problem = plan_core.check_size(settings["width"], settings["height"])
        if problem:
            raise StudioError(_t("engine.branch", v0=branch['name'], problem=problem))
        # LoRA added for this take: the exact list given, otherwise the branch's (on top of the project stack)
        extra_loras = projects.merge_loras(projects.clean_loras(take_loras)) if take_loras is not None else projects.default_extra_loras(branch)
        if extra_loras:
            base = [{"name": l["name"], "strength": float(l["strength"])} for l in projects.active_loras(settings)]
            settings = dict(settings, loras=[dict(l, enabled=True) for l in projects.merge_loras(base, extra_loras)])
        # latent upscale: this take's settings when given, otherwise the branch's
        up_settings, up_source = projects.upscale_of(branch), "branch"
        if upscale_settings is not None:
            up_settings, up_source = projects.clean_upscale(upscale_settings), "take"
        upscale = upscale_plan(up_settings, settings["width"], settings["height"], settings["steps"]) if up_settings["enabled"] else None
        if upscale and extra_loras and upscale.get("pass2_loras") is not None:   # own LoRA for pass 2: the take's are added
            base2 = [{"name": l["name"], "strength": float(l["strength"])} for l in projects.active_loras({"loras": upscale["pass2_loras"]})]
            upscale["pass2_loras"] = [dict(l, enabled=True) for l in projects.merge_loras(base2, extra_loras)]
        context_latent = 0
        if upscale and clip["continue"]:     # clip 1 too when it continues the start video
            context = int(plan_core.timeline(plan)[index - 1]["context"])
            context_latent = latent_frames(context) if context else 0
        refs, problems = clip_needs(plan, index, {"refs": projects.effective_refs(path, branch, plan), "song": branch.get("song") or ""})
        if problems:
            raise StudioError(_t("engine.clip_references_button_of_branch", index=index, v1=', '.join(problems), v2=branch['name']))

        if forced_seed is not None:
            if not 0 <= forced_seed <= 2 ** 48:
                raise StudioError(_t("engine.invalid_seed_an_integer_from_0"))
            seed = forced_seed
        else:
            seed = random.getrandbits(48)
        token = uuid.uuid4().hex[:8]
        take_id = f"s{seed}_{token}"

        # frozen now (what was clicked is what will be generated); sent to ComfyUI when its turn comes
        try:
            info = self._object_info()
        except comfy.ComfyError as exc:
            raise StudioError(str(exc)) from exc
        missing = missing_nodes(info, settings, music=not free, upscale=upscale,
                                video=any(r.get("video") for r in refs))
        if missing:
            raise StudioError(_t("engine.nodes_missing_from_comfyui") + ", ".join(missing)
                              + (_t("engine.kjnodes_preview_install_comfyui_kjnodes_or")
                                 if "ModelPreviewOverrideKJ" in missing else "")
                              + (_t("engine.video_node_needs_plugin") if "H3PlanVideo" in missing else ""))
        if extra_loras:
            known_loras = set(((((info.get("LoraLoaderModelOnly") or {}).get("input") or {}).get("required") or {}).get("lora_name") or [[]])[0] or [])
            unknown = [l["name"] for l in extra_loras if known_loras and l["name"] not in known_loras]
            if unknown:
                raise StudioError(_t("engine.lora_not_found_in_comfyui") + ", ".join(unknown))
        settings = dict(settings, _kj_frames_value=kj_frames_value(info, settings))
        files = {}
        for ref in refs:
            files[ref["name"]] = {"image": None, "voice": None, "image_sha": None, "voice_sha": None}
            for kind in ("image", "voice", "video"):
                if ref.get(kind):
                    local_file = projects.safe_join(path, ref[kind])
                    if not local_file.is_file():
                        raise StudioError(_t("engine.file_of_not_found", v0=ref['name'], v1=ref[kind]))
                    files[ref["name"]][kind] = ref[kind]
                    files[ref["name"]][kind + "_sha"] = takes.file_sha(local_file)
        song_sha = None
        if not free:
            song_file = projects.safe_join(path, branch["song"])
            if not song_file.is_file():
                raise StudioError(_t("engine.song_not_found", v0=branch['song']))
            song_sha = takes.file_sha(song_file)
        cont = clip["continue"] and index > 1
        spec = {"raw": raw, "mode": plan["mode"], "refs": [r["name"] for r in refs], "files": files,
                "song": None if free else branch["song"], "song_sha": song_sha,
                "parent_take": after if cont and after in known else None,
                "settings": settings, "upscale": upscale, "context_latent": context_latent}

        instruction = ((raw.get("edit_video") or {}) if isinstance(raw.get("edit_video"), dict) else {}).get("instruction")
        studio_info = {
            "branch": branch_id,
            "refs": {n: {"image": f["image_sha"], "voice": f["voice_sha"], **({"video": f["video_sha"]} if f.get("video") else {})}
                     for n, f in files.items()},
            "files": {n: {"image": f["image"], "voice": f["voice"], **({"video": f["video"]} if f.get("video") else {})}
                      for n, f in files.items()},
            "width": int(settings["width"]), "height": int(settings["height"]),
            "ref_image_size": branch.get("ref_image_size") or projects.DEFAULT_REF_SIZE,
            **({"song": song_sha, "song_file": branch["song"]} if not free else {}),
            "models": dict({k: settings.get(k) for k in ("unet_name", "weight_dtype", "clip_name", "video_vae", "audio_vae",
                                                         "sampler_name", "scheduler", "steps", "shift_video", "shift_audio",
                                                         "attention")},
                           loras=[{"name": l["name"], "strength": l["strength"]} for l in projects.active_loras(settings)]),
            "extra_loras": extra_loras,
            # the portion of plan this take is made with, and the take before it: a take never changes
            "portion": {"clip": entry, "edit_instruction": instruction if isinstance(instruction, str) else None,
                        "refs_desc": {n: (raw.get("refs") or {}).get(n) for n in entry.get("refs") or []}},
            "predecessor": after,
            "raw_start": plan_core.timeline(plan)[index - 1]["raw_start"],
        }
        if upscale:
            studio_info["upscale"] = {k: upscale[k] for k in ("summary", "upscaler", "model", "w0", "h0", "start_mp", "steps",
                                                             "pass1", "pass2", "pass2_loras", "pass2_sampler")}
            studio_info["upscale"].update(settings={k: v for k, v in up_settings.items() if k != "enabled"}, source=up_source)
        job = {"units": int(settings["width"]) * int(settings["height"]) * int(clip["frames"]) / 1e6,
               "steps": sum(upscale["steps"]) if upscale else int(settings["steps"]), "upscale": bool(upscale),
               "id": "j" + uuid.uuid4().hex[:15], "prompt_id": None, "dispatched": False, "spec": spec,
               "project": name, "branch": branch_id, "kind": "clip", "clip": index, "token": token, "take_id": take_id,
               "frames": int(clip["frames"]),
               "parentToken": after.split("_")[-1] if cont and after else None,
               "parentJob": after_job, "seed": seed, "status": "queued", "loras": extra_loras,
               "progress": None, "step": None, "error": None, "take": None, "created": time.time(), "studio": studio_info,
               "lot": lot, "lot_label": lot_label}
        # what comes after the new take: the suite of the twig it was taken from (its clips after this one)
        plans.set_suite(path, take_id, index, plans.suite_from(raw, index))
        with self.lock:
            self.jobs[job["id"]] = job
            self._enqueue(job)
            self._save(name)
        self.wake.set()
        return self._public(job)

    # ------------------------------------------------------------------ sending a job to ComfyUI
    def _dispatch_clip(self, client, job):
        """Sends what a frozen generation needs (plan, references, song, takes continued) and queues it."""
        name, branch_id, spec = job["project"], job["branch"], job["spec"]
        path, raw, index = self._project(name), spec["raw"], job["clip"]
        with self.lock:
            others = [j for j in self.jobs.values() if j is not job and j["project"] == name and _branch(j) == branch_id
                      and (j.get("dispatched") and j["status"] in ACTIVE or j["status"] == "harvest")]
        if not others:
            self._purge_branch(client, name, branch_id)        # nothing left over from earlier sessions
        plan_file = self._send_plan(client, name, branch_id, raw)
        sent_refs = []
        for ref_name in spec["refs"]:
            f = spec["files"].get(ref_name) or {}
            item = {"name": ref_name, "image": None, "voice": None, "video": None}
            for kind in ("image", "voice", "video"):
                if f.get(kind):
                    local_file = projects.safe_join(path, f[kind])
                    if not local_file.is_file() or takes.file_sha(local_file) != f.get(kind + "_sha"):
                        raise StudioError(_t("engine.the_file_of_has_changed_or", ref_name=ref_name, v1=f[kind]))
                    item[kind] = self._send_input(client, local_file, f[kind + "_sha"], f"{INPUT_DIR}/{name}", job=job)
            sent_refs.append(item)
        song = None
        if spec.get("song"):
            song_file = projects.safe_join(path, spec["song"])
            if not song_file.is_file() or takes.file_sha(song_file) != spec.get("song_sha"):
                raise StudioError(_t("engine.the_song_has_changed_or_disappeared", v0=spec['song']))
            song = self._send_input(client, song_file, spec["song_sha"], "", prefix=f"{INPUT_DIR}_{name}_")
        if spec.get("parent_take"):
            self._send_chain(client, name, branch_id, path, raw, index - 1, spec["parent_take"])
        elif job.get("parentToken"):
            self._send_job_chain(client, name, branch_id, path, raw, job)
        workflow = clip_workflow({
            "plan_file": plan_file, "clip_index": index, "mode": spec["mode"], "refs": sent_refs, "song": song,
            "take_token": job["token"], "parent_token": job.get("parentToken") or "", "seed": job["seed"],
            "settings": spec["settings"], "upscale": spec.get("upscale"), "context_latent": spec.get("context_latent") or 0,
        })
        return client.queue_prompt(workflow, self.client_id, {"project": name, "clip": index, "token": job["token"]})

    def _resolve_assembly(self, job):
        """The takes of a planned assembly (generations it waited for), known only now."""
        for clip_key, jid in list((job.get("pending") or {}).items()):
            other = self.jobs.get(jid)
            if not other or not other.get("take"):
                raise StudioError(_t("engine.the_take_of_clip_does_not", clip_key=clip_key))
            job["takes"][clip_key] = other["take"]

    def _local_assemblies(self):
        """Assemblies Encore makes itself with ffmpeg from the takes' previews, beside ComfyUI's work (one at a
        time). One that cannot (no ffmpeg, a take without preview, invalidated takes) goes to the plugin."""
        self._sweep_orphans()
        with self.lock:
            if self.paused or any(j.get("local") and j["status"] == "running" for j in self.jobs.values()):
                return
            job = next((self.jobs[i] for i in self.order if i in self.jobs and self.jobs[i]["kind"] == "assemble"
                        and self.jobs[i].get("local") is not False and self._ready(self.jobs[i])), None)
            if job is None:
                return
            try:
                self._resolve_assembly(job)
            except (StudioError, OSError, ValueError) as exc:
                return self._fail(job, str(exc))
            path = self._project(job["project"])
            ffmpeg, why = assembler.ready_for(path, job, self.studio.config)
            if ffmpeg is None:
                job["local"] = False
                print(f"[Encore] assembly {job['export']} by the plugin: {why}", flush=True)
                self._save(job["project"])
                return
            job.update(local=True, status="running", t_start=time.time(), step=_t("assembler.step", pct=0),
                       progress={"value": 0, "max": 100})
            if job["id"] in self.order:
                self.order.remove(job["id"])
            self._save(job["project"])
            self._save_queue()
        threading.Thread(target=self._run_local_assembly, args=(job, path, ffmpeg), daemon=True,
                         name=f"encore-assemble-{job['id']}").start()

    def _run_local_assembly(self, job, path, ffmpeg):
        def progress(share):
            pct = int(100 * share)
            job["step"], job["progress"] = _t("assembler.step", pct=pct), {"value": pct, "max": 100}
        try:
            target = path / "exports" / f"{job['export']}.mp4"
            report = assembler.build(path, job, ffmpeg, target, on_progress=progress, procs=self.local_procs)
            if job["id"] not in self.jobs:          # cancelled meanwhile
                target.unlink(missing_ok=True)
                return
            self._write_export(path, job, report)
            with self.lock:
                job["status"], job["ended"], job["progress"], job["step"] = "done", time.time(), None, None
                self._save(job["project"])
        except Exception as exc:  # noqa: BLE001 - the job shows the error
            if job["id"] in self.jobs:
                self._fail(job, str(exc))
        finally:
            self.wake.set()

    def _write_export(self, path, job, report):
        """The information file of an assembled video (exports/<name>.json and its infos)."""
        info = {"name": job["export"], "created": time.time(), "branch": job.get("branch"), "branch_name": job.get("branch_name"),
                "clips": job.get("clips"), "takes": {str(k): v for k, v in (job.get("takes") or {}).items()},
                "size": job.get("size"), "report": report, "prompt_id": job.get("prompt_id"),
                "assembled_by": "ffmpeg" if job.get("local") else "plugin"}
        meta = path / "exports" / f"{job['export']}.json"
        tmp = meta.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, meta)
        try:
            write_infos(path, job, report)
        except Exception as exc:          # never lose a video because of its information file
            print(_t("engine.encore_infos_of_not_written", v0=job['export'], exc=exc), flush=True)

    def _dispatch_assembly(self, client, job):
        name, spec = job["project"], job["spec"]
        path, raw, workspace = self._project(name), spec["raw"], job["workspace"]
        self._resolve_assembly(job)
        plan_file = self._send_plan(client, name, workspace, raw, settings_branch=job["branch"])
        chosen = {int(k): v for k, v in job["takes"].items()}
        sent_plan = plan_core.normalize(json.loads(json.dumps(raw)))
        for index in range(1, job["clips"] + 1):
            meta = takes.clip_dir(path, index) / f"{chosen[index]}.json"
            try:
                record = dict(json.loads(meta.read_text(encoding="utf-8")), id=chosen[index])
            except (OSError, ValueError) as exc:
                raise StudioError(_t("engine.take_of_clip_has_disappeared_since", v0=chosen[index], index=index)) from exc
            # the record matches the plan sent (the plan of the twig, as its takes were made)
            record = takeplan.rewritten_record(sent_plan, index, record, record.get("parent"))
            self._send_take(client, name, workspace, path, index, record)
        client.save_selection(plan_file, chosen)
        song = None
        if spec.get("song"):
            song_file = projects.safe_join(path, spec["song"])
            if not song_file.is_file():
                raise StudioError(_t("engine.song_not_found", v0=spec['song']))
            song = self._send_input(client, song_file, takes.file_sha(song_file), "", prefix=f"{INPUT_DIR}_{name}_")
        start_video = None
        if spec.get("start_video"):
            sv = spec["start_video"]
            video_file = projects.safe_join(path, sv["video"])
            if not video_file.is_file() or takes.file_sha(video_file) != sv["sha"]:
                raise StudioError(_t("engine.the_file_of_has_changed_or", ref_name=sv["name"], v1=sv["video"]))
            start_video = {"name": sv["name"], "video": self._send_input(client, video_file, sv["sha"], f"{INPUT_DIR}/{name}", job=job)}
        edit_video = None
        if spec.get("edit_video"):
            ev = spec["edit_video"]
            video_file = projects.safe_join(path, ev["video"])
            if not video_file.is_file() or takes.file_sha(video_file) != ev["sha"]:
                raise StudioError(_t("engine.the_file_of_has_changed_or", ref_name=ev["name"], v1=ev["video"]))
            edit_video = {"name": ev["name"], "video": self._send_input(client, video_file, ev["sha"], f"{INPUT_DIR}/{name}", job=job)}
        workflow = assemble_workflow(plan_file, spec["mode"], job["clips"], spec["settings"], song,
                                     start_video=start_video, size=job.get("size"), edit_video=edit_video)
        return client.queue_prompt(workflow, self.client_id, {"project": name, "kind": "assemble", "branch": job["branch"]})

    def _ready(self, job):
        """Can this waiting job be sent? (the generation it continues must be over and harvested)"""
        if job.get("suspended"):
            return False
        for dep in self._deps(job):
            other = self.jobs.get(dep)
            if other is not None and other["status"] != "done":
                return False
            if other is None and dep in (job.get("pending") or {}).values():
                return False          # cannot know its take any more: _sweep_orphans fails it
        return True

    def _sweep_orphans(self):
        """Waiting jobs whose dependency failed (or vanished before giving its take) cannot run: error, with their
        own dependents. Only them: what does not depend on the failed generation keeps going."""
        with self.lock:
            doomed = []
            for jid in self.order:
                job = self.jobs.get(jid)
                if not job:
                    continue
                for dep in self._deps(job):
                    other = self.jobs.get(dep)
                    if (other is not None and other["status"] == "error") or (other is None and dep in (job.get("pending") or {}).values()):
                        clip = other.get("clip") if other else None
                        doomed.append((job, _t("engine.clip_it_depends_on_has_failed_2", clip=clip) if clip else _t("engine.a_generation_it_depends_on_did")))
                        break
        for job, message in doomed:
            if job["status"] in ACTIVE:
                self._fail(job, message)

    def _dispatch_next(self):
        """One job at a time in ComfyUI: when ours are all over, the first ready job of the queue is sent."""
        self._sweep_orphans()
        with self.launch_lock:
            with self.lock:
                if self.paused or any(j.get("dispatched") and j["status"] in ACTIVE for j in self.jobs.values()):
                    return
                if any(j["status"] == "harvest" for j in self.jobs.values()):
                    return
                job = next((self.jobs[i] for i in self.order if i in self.jobs and self._ready(self.jobs[i])
                            and not (self.jobs[i]["kind"] == "assemble" and self.jobs[i].get("local") is not False)), None)
                if job is None:
                    return
            client = self.client
            self._ensure_socket()
            try:
                answer = self._dispatch_assembly(client, job) if job["kind"] == "assemble" else self._dispatch_clip(client, job)
            except comfy.ComfyError as exc:
                if exc.unreachable:
                    self._comfy_down()
                    return                              # ComfyUI unreachable: try again later
                return self._fail(job, str(exc))
            except (StudioError, OSError, ValueError) as exc:
                return self._fail(job, str(exc))
            with self.lock:
                job.update(prompt_id=answer["prompt_id"], dispatched=True, dispatched_at=time.time())
                if job["id"] in self.order:
                    self.order.remove(job["id"])
                self._save(job["project"])
                self._save_queue()

    def _fail(self, job, message):
        """A job that cannot run: error, and the jobs that depend on it are taken out of the queue."""
        with self.lock:
            job.update(status="error", error=message)
            dependents = self._dependents(job["id"])
            for jid in dependents:
                self.jobs[jid].update(status="error", error=_failed_dep(job))
            for jid in [job["id"]] + dependents:
                if jid in self.order:
                    self.order.remove(jid)
            for name in {job["project"]}:
                self._save(name)
            self._save_queue()

    def _send_plan(self, client, name, branch, raw, settings_branch=None):
        copy = json.loads(json.dumps(raw))
        copy["project"] = mirror_name(name, branch)
        meta = projects.read_meta(self._project(name))
        copy["ref_image_size"] = next((b.get("ref_image_size") for b in meta["branches"] if b["id"] == (settings_branch or branch)), None) \
            or projects.DEFAULT_REF_SIZE        # a branch setting: the plan does not hold it any more
        # version 5 only for an edited video: plans without one stay readable by the plugin 3.7
        copy["version"] = plan_core.PLAN_VERSION if copy.get("edit_video") else 4
        data = (json.dumps(copy, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        return self._put(client, data, "plan.json", f"{INPUT_DIR}/{name}/{branch}", "input")

    def _send_input(self, client, local_file: Path, sha, subfolder, prefix="", job=None):
        """A project file in ComfyUI's input folder, named after its content (sent once; a big file shows its
        progress on the job)."""
        stem, ext = os.path.splitext(local_file.name)
        name = f"{prefix}{stem[:40]}_{sha[:10]}{ext.lower()}"
        key = (self.studio.config["comfy_url"], subfolder, name)
        if self.uploaded.get(key) != sha:
            def progress(sent, total):
                if job is not None and total > 8 * 1024 * 1024:
                    job["step"] = _t("engine.sending_to_comfyui", file=local_file.name, v1=int(100 * sent / total))
            self._put(client, local_file, name, subfolder, "input", progress, named_by_content=True)
            self.uploaded[key] = sha
        return f"{subfolder}/{name}" if subfolder else name

    def _put(self, client, data, name, subfolder, kind, progress=None, named_by_content=False):
        """A file (bytes, or the path of a file) into ComfyUI's input or output folder; returns its path there.
        When ComfyUI's folder is known (configuration) the file is written straight into it: no size limit. Otherwise,
        or if ComfyUI does not see that copy (another input folder, another machine), it goes through ComfyUI's upload
        route, which refuses files over its --max-upload-size (100 MB by default)."""
        rel = f"{subfolder}/{name}" if subfolder else name
        if self._copy_into(client, data, name, subfolder, kind, progress, named_by_content):
            return rel
        try:
            return client.upload(data, name, subfolder, kind, progress=progress)
        except comfy.ComfyError as exc:
            if exc.status == 413:
                size = len(data) if isinstance(data, (bytes, bytearray)) else Path(data).stat().st_size
                label = name if isinstance(data, (bytes, bytearray)) else Path(data).name
                raise StudioError(_t("engine.upload_too_big", file=label, v1=f"{size / 1024 ** 2:.0f}")) from exc
            raise

    def _copy_into(self, client, data, name, subfolder, kind, progress, named_by_content):
        root = comfy_setup.comfy_root(self.studio.config.get("comfy_dir"))
        if root is None:
            return False
        folder = root / kind / subfolder if subfolder else root / kind
        target = folder / name
        try:
            size = len(data) if isinstance(data, (bytes, bytearray)) else Path(data).stat().st_size
            if not (named_by_content and target.is_file() and target.stat().st_size == size):
                folder.mkdir(parents=True, exist_ok=True)
                part = target.with_name(target.name + ".part")
                if isinstance(data, (bytes, bytearray)):
                    part.write_bytes(data)
                else:
                    sent = 0
                    with open(data, "rb") as src, open(part, "wb") as dst:
                        for chunk in iter(lambda: src.read(8 * 1024 * 1024), b""):
                            dst.write(chunk)
                            sent += len(chunk)
                            if progress:
                                progress(sent, size)
                os.replace(part, target)
        except OSError:
            return False
        return client.exists(name, subfolder, kind)

    def _send_take(self, client, name, branch, path, index, record):
        """A take into a working copy in ComfyUI: its latent once, its record every time (it is rewritten to match
        the plan sent with each generation or assembly)."""
        key = (index, record["id"])
        present = self._mirror(name, branch)
        pt, meta, _mp4 = takes.take_files(path, index, record["id"])
        sub = f"h3_clip_plan/{mirror_name(name, branch)}/latents/clip_{index:03d}"
        if key not in present:
            self._put(client, pt, pt.name, sub, "output")
        data = {k: v for k, v in record.items() if k != "id"}
        self._put(client, json.dumps(data, indent=1).encode("utf-8"), meta.name, sub, "output")
        present.add(key)

    def _send_chain(self, client, name, branch, path, raw, index, take_id):
        """The takes a generation continues (up to the start of their scene), with records matching its plan."""
        try:
            chain = takes.ancestors(path, raw, index, take_id)
        except ValueError as exc:
            raise StudioError(str(exc)) from exc
        sent_plan = plan_core.normalize(json.loads(json.dumps(raw)))
        for number, record in reversed(chain):
            record = dict(takeplan.rewritten_record(sent_plan, number, record, record.get("parent")), id=record["id"])
            self._send_take(client, name, branch, path, number, record)

    def _send_job_chain(self, client, name, branch, path, raw, job):
        """The takes a generation continues when it was launched after a generation then still waiting."""
        if not job.get("parentToken"):
            return
        local = takes.list_takes(path).get(job["clip"] - 1, [])
        record = next((r for r in local if r["id"].endswith("_" + job["parentToken"])), None)
        if record is None:
            raise StudioError(_t("engine.the_take_of_clip_this_clip", v0=job["clip"] - 1))
        return self._send_chain(client, name, branch, path, raw, job["clip"] - 1, record["id"])

    # ------------------------------------------------------------------ following the generations
    def _running_job(self, prompt_id=None):
        with self.lock:
            job = self._by_prompt(prompt_id)
            if job:
                return job
            running = [j for j in self.jobs.values() if j["status"] == "running" and j.get("dispatched")]
            return running[0] if len(running) == 1 else None

    def _keep_preview(self, job, data, mime):
        with self.lock:
            self.previews[job["id"]] = (data, mime)
            job["preview"] = (job.get("preview") or 0) + 1
            job["previewMime"] = mime

    def _logging(self):
        return self.diagnostic is not None and any(j["status"] in ACTIVE for j in self.jobs.values())

    def _on_binary(self, payload):
        info = comfy.parse_binary(payload)
        if self._logging():
            self.diagnostic.binary_message(info, payload)
        if info.get("image"):
            job = self._running_job((info.get("metadata") or {}).get("prompt_id"))
            if job and job["status"] in ACTIVE:
                self._keep_preview(job, info["image"], info.get("mime") or comfy.sniff_mime(info["image"]))

    def _images_in(self, value, found):
        """data:image/... strings inside a JSON message (custom preview widgets send them this way)."""
        if isinstance(value, str) and value.startswith("data:image/") and ";base64," in value:
            head, _, body = value.partition(";base64,")
            try:
                found.append((base64.b64decode(body), head[5:]))
            except ValueError:
                pass
        elif isinstance(value, dict):
            for v in value.values():
                self._images_in(v, found)
        elif isinstance(value, list):
            for v in value:
                self._images_in(v, found)
        return found

    def _on_event(self, msg):
        data = msg.get("data") or {}
        kind = msg.get("type")
        if self._logging():
            self.diagnostic.json_message(msg)
        if kind == "kj_preview_override" and isinstance(data, dict) and data.get("image"):
            try:
                image = base64.b64decode(data["image"])
            except ValueError:
                image = None
            if image:
                mime = data.get("mime") or "image/jpeg"
                if self._logging():
                    saved = self.diagnostic.save_image(image, mime, "kj")
                    self.diagnostic.note(_t("engine.kjnodes_preview_step_bytes_x_fps", v0=data.get('step'), v1=data.get('total'), mime=mime, v3=len(image), v4=data.get('w'), v5=data.get('h'), v6=data.get('fps'), v7=data.get('audio')) + (f" -> {saved}" if saved else ""))
                job = self._running_job()
                if job and job["status"] in ACTIVE:
                    self._keep_preview(job, image, mime)
            return
        if kind not in ("status", "progress", "executing", "execution_start", "execution_cached", "executed",
                        "execution_success", "execution_error", "execution_interrupted", "progress_state", "crystools.monitor"):
            images = self._images_in(data, [])
            if images:
                job = self._running_job(data.get("prompt_id") if isinstance(data, dict) else None)
                if self._logging():
                    for img, mime in images:
                        saved = self.diagnostic.save_image(img, mime, f"json_{kind}")
                        self.diagnostic.note(_t("engine.image_in_the_json_message_bytes", kind=kind, mime=mime, v2=len(img), v3=image_size(img)) + (f" -> {saved}" if saved else ""))
                if job and job["status"] in ACTIVE:
                    self._keep_preview(job, images[-1][0], images[-1][1])
        if kind == "status":
            self.wake.set()
            return
        prompt_id = data.get("prompt_id")
        with self.lock:
            job = self._by_prompt(prompt_id)
            if not job or job["status"] not in ACTIVE:
                return
            now = time.time()
            if kind == "execution_start":
                job["status"] = "running"
                job["step"] = job.get("step") or _t("engine.preparing")
                job.setdefault("t_start", now)
            elif kind == "executing":
                if data.get("node") is None:
                    self.wake.set()
                else:
                    job["status"] = "running"
                    job.setdefault("t_start", now)
                    node = str(data.get("node"))
                    job["step"] = _t(STEP_KEYS[node]) if node in STEP_KEYS else (job.get("step") or _t("engine.preparing"))
                    if node == "25":
                        job.setdefault("t_sample", now)
                    elif node in ("26", "27", "28") and job.get("t_sample"):
                        job.setdefault("t_sample_end", now)
            elif kind == "progress":
                job["status"] = "running"
                job.setdefault("t_start", now)
                job["progress"] = {"value": data.get("value"), "max": data.get("max")}
                if str(data.get("node")) == "25" and data.get("value"):
                    job.setdefault("t_sample", now)
                    job["t_step"] = [int(data["value"]), int(data.get("max") or 0), now]
                if str(data.get("node")) in STEP_KEYS:
                    job["step"] = _t(STEP_KEYS[str(data.get("node"))])
            elif kind in ("execution_success", "execution_error", "execution_interrupted"):
                self.wake.set()

    def _poll_loop(self):
        while True:
            self.wake.wait(1.0)
            self.wake.clear()
            try:
                self._poll()
            except Exception:  # noqa: BLE001 - keep following
                time.sleep(1.0)

    def _poll(self):
        self._follow()
        self._local_assemblies()
        self._dispatch_next()

    def _follow(self):
        with self.lock:
            active = [j for j in self.jobs.values() if j["status"] in ACTIVE and j.get("dispatched")]
            pending = [j for j in self.jobs.values() if j["status"] == "harvest"]
        if not active and not pending:
            return
        client = self.client
        try:
            state = client.queue_state()
        except comfy.ComfyError as exc:
            if exc.unreachable:
                self._comfy_down()
            return
        running = {row[1] for row in state.get("queue_running") or []}
        queued = {row[1] for row in state.get("queue_pending") or []}
        self._count_foreign(state)
        touched = set()
        for job in active:
            pid = job["prompt_id"]
            if pid in running:
                if job["status"] != "running":
                    job["status"] = "running"
                    job["step"] = job.get("step") or _t("engine.preparing")
                continue
            if pid in queued:
                continue
            try:
                entry = client.history(pid).get(pid)
            except comfy.ComfyError:
                continue
            if job.get("requeue") and entry is not None:       # interrupted by « pause immédiate »
                self._requeue(job)
                continue
            with self.lock:
                if entry is None:
                    job["missing"] = job.get("missing", 0) + 1
                    if job.get("requeue") and job["missing"] >= 2:      # interrupted before it started
                        self._requeue(job)
                        continue
                    restarted = (self.comfy_down_at or 0) > (job.get("dispatched_at") or 0)
                    if job["missing"] >= 5 and restarted and job.get("lost", 0) < 2:   # ComfyUI restarted: its queue is gone
                        job["lost"] = job.get("lost", 0) + 1
                        self._requeue(job)
                        continue
                    if job["missing"] >= 5:
                        job["status"], job["error"] = "error", _t("engine.gone_from_the_comfyui_queue_comfyui")
                        for jid in self._dependents(job["id"]):
                            self.jobs[jid].update(status="error", error=_failed_dep(job))
                            if jid in self.order:
                                self.order.remove(jid)
                        touched.add((job["project"], _branch(job)))
                    continue
                status = (entry.get("status") or {})
                if status.get("status_str") == "error" or not status.get("completed", True):
                    messages = status.get("messages") or []
                    err = next((m[1] for m in messages if m and m[0] == "execution_error"), None)
                    interrupted = any(m and m[0] == "execution_interrupted" for m in messages)
                    job["status"] = "error"
                    job["error"] = _t("engine.interrupted") if interrupted and not err else (
                        f"{err.get('node_type', '')} : {err.get('exception_message', _t('engine.error'))}".strip() if err else _t("engine.error"))
                    for jid in self._dependents(job["id"]):
                        self.jobs[jid].update(status="error", error=_failed_dep(job))
                        if jid in self.order:
                            self.order.remove(jid)
                    self._save_queue()
                else:
                    job["status"] = "harvest"
                    pending.append(job)
                touched.add((job["project"], _branch(job)))
        for job in pending:
            self._harvest(client, job)
            touched.add((job["project"], _branch(job)))
        with self.lock:
            for name in {n for n, _b in touched}:
                self._save(name)
        for name, branch in touched:
            self._purge_if_idle(client, name, branch)
        finished_assemblies = [j for j in active + pending if j.get("kind") == "assemble" and j["status"] in ("done", "error")]
        for job in finished_assemblies:
            self._purge_workspace(client, job)

    def _harvest(self, client, job):
        if job.get("kind") == "assemble":
            return self._harvest_assembly(client, job)
        name, branch = job["project"], _branch(job)
        try:
            path = self._project(name)
            plan_file = plan_file_of(name, branch)
            listing = client.takes(plan_file)
            entry = next((c for c in listing.get("clips") or [] if c["index"] == job["clip"]), None)
            take = next((t for t in (entry or {}).get("takes") or [] if t["id"].endswith("_" + job["token"])), None)
            if take is None:
                raise StudioError(_t("engine.generation_finished_but_the_take_cannot"))
            take_id = take["id"]
            pt, meta, mp4 = takes.take_files(path, job["clip"], take_id)
            sub = f"h3_clip_plan/{mirror_name(name, branch)}/latents/clip_{job['clip']:03d}"
            client.download(pt.name, sub, str(pt))
            if take.get("preview"):
                pv = take["preview"]
                client.download(pv["filename"], pv["subfolder"], str(mp4), pv.get("type", "output"))
            record = {k: v for k, v in (take.get("record") or {}).items() if k != "id"}
            record["studio"] = dict(job.get("studio") or {}, prompt_id=job.get("prompt_id"))
            tmp = meta.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, meta)
            try:
                # the new take is chosen (with its twig), unless the selection is in another branch
                if takes.read_selection(path).get("branch") in (None, branch):
                    takes.select_chain(path, None, job["clip"], take_id, branch=branch, fits=plans.fits_map(path))
            except (ValueError, IndexError, KeyError, StudioError):
                pass
            with self.lock:
                self._mirror(name, branch).add((job["clip"], take_id))
                job["status"], job["take"], job["ended"] = "done", take_id, time.time()
                for other in self.jobs.values():               # planned assemblies waiting for this take
                    pending = other.get("pending") or {}
                    for clip_key, jid in list(pending.items()):
                        if jid == job["id"]:
                            other["takes"][clip_key] = take_id
                            del pending[clip_key]
                            self._save(other["project"])
                self._record_timing(job)
                job["progress"] = None
                self.previews.pop(job["id"], None)
        except (StudioError, comfy.ComfyError, OSError, ValueError) as exc:
            with self.lock:
                job["harvest_tries"] = job.get("harvest_tries", 0) + 1
                if job["harvest_tries"] >= 3:
                    job["status"], job["error"] = "error", _t("engine.cannot_collect_the_take", exc=exc)

    def _harvest_assembly(self, client, job):
        name = job["project"]
        try:
            path = self._project(name)
            entry = client.history(job["prompt_id"]).get(job["prompt_id"]) or {}
            outputs = (entry.get("outputs") or {}).get("10") or {}
            files = [f for f in (outputs.get("gifs") or outputs.get("videos") or outputs.get("images") or [])
                     if str(f.get("filename", "")).lower().endswith((".mp4", ".webm", ".mov", ".mkv"))]
            if not files:
                raise StudioError(_t("engine.assembly_finished_but_the_video_cannot"))
            video = files[-1]
            target = path / "exports" / f"{job['export']}.mp4"
            client.download(video["filename"], video.get("subfolder", ""), str(target), video.get("type", "output"))
            report = (outputs.get("text") or [""])[0]
            self._write_export(path, job, report)
            with self.lock:
                job["status"], job["ended"], job["progress"] = "done", time.time(), None
                self._record_timing(job)
        except (StudioError, comfy.ComfyError, OSError, ValueError) as exc:
            with self.lock:
                job["harvest_tries"] = job.get("harvest_tries", 0) + 1
                if job["harvest_tries"] >= 3:
                    job["status"], job["error"] = "error", _t("engine.cannot_collect_the_video", exc=exc)

    def _purge_workspace(self, client, job):
        """The ComfyUI copy made for one assembly: of no use once it is over."""
        workspace = job.get("workspace")
        if not workspace or not self.studio.config.get("purge_comfy_copy", True):
            return
        name = job["project"]
        try:
            listing = client.takes(plan_file_of(name, workspace))
            items = [{"clip": c["index"], "id": t["id"]} for c in listing.get("clips") or [] for t in c.get("takes") or []]
            if items:
                client.delete_takes(plan_file_of(name, workspace), items)
        except (StudioError, comfy.ComfyError, OSError, ValueError):
            pass
        self.mirror.pop((name, workspace), None)

    def _purge_branch(self, client, name, branch):
        if not self.studio.config.get("purge_comfy_copy", True):
            return
        try:
            listing = client.takes(plan_file_of(name, branch))
            items = [{"clip": c["index"], "id": t["id"]} for c in listing.get("clips") or [] for t in c.get("takes") or []]
            if items:
                client.delete_takes(plan_file_of(name, branch), items)
        except (StudioError, comfy.ComfyError, OSError, ValueError):
            pass
        self.mirror[(name, branch)] = set()

    def _purge_if_idle(self, client, name, branch):
        if not self.studio.config.get("purge_comfy_copy", True):
            return
        with self.launch_lock:
            with self.lock:
                mine = [j for j in self.jobs.values() if j["project"] == name and _branch(j) == branch]
                if any(j["status"] in ACTIVE + ("harvest",) for j in mine):
                    return
                # takes whose copy into the project failed are kept (their files can still be fetched by hand)
                keep = {j["token"] for j in mine if j.get("harvest_tries")}
            try:
                listing = client.takes(plan_file_of(name, branch))
                items = [{"clip": c["index"], "id": t["id"]} for c in listing.get("clips") or [] for t in c.get("takes") or []
                         if t["id"].split("_")[-1] not in keep]
                if items:
                    client.delete_takes(plan_file_of(name, branch), items)
                self.mirror[(name, branch)] = set()
            except (StudioError, comfy.ComfyError, OSError, ValueError):
                pass


def _branch(job):
    return job.get("branch") or "b1"     # generations started before branches existed
