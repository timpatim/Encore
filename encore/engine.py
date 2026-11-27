"""Encore - generations: the Studio decides, ComfyUI only computes.

For each generation the Studio (0.50: without the ComfyUI-H3-ClipPlan plugin)
  1. composes the clip's H3 prompt and prepares its files with ffmpeg (prepare.py: voices cut to H3's limits,
     the song shifted on the plan's timeline, the end of the start video or the slice of the edited video);
  2. sends them to ComfyUI, with the latent of the take it continues;
  3. builds the workflow (ComfyUI's own nodes, MultiRef, VHS: workflows.clip_workflow) and queues it; ComfyUI does
     all the inference;
  4. follows it (websocket for the progress, /queue and /history for the end);
  5. fetches the new take (latent, preview) into the project, writes its record and chooses it.

ComfyUI's side, under names of its own:
    input/encore/<project>/ (pictures), input/encore_<project>_* (voices, song, pieces of video)
    output/encore/<project>/ (latents sent, takes and previews made)
When no generation of the project is waiting any more, Encore empties it (configurable), when it knows ComfyUI's
folder: ComfyUI cannot delete files through its API.
"""
from __future__ import annotations

from .i18n import t as _t
import base64
import json
import os
import random
import threading
import traceback
import time
import uuid
from pathlib import Path

from . import assembler, comfy, comfy_setup, latents, plan_core, plans, prepare, previews, projects, takeplan, takes
from .diagnostic import Diagnostic, image_size
from .exports import export_name, write_infos
from .projects import StudioError
from .workflows import (clip_needs, clip_workflow, kj_frames_value, latent_frames, missing_nodes, ref_inputs,
                        saved_latent_name, upscale_plan)

# ComfyUI's side (0.50): input/encore/<project>/ (pictures), input/encore_<project>_* (voices, song, pieces of video),
# output/encore/<project>/latents (takes continued), takes, previews (what a generation makes, fetched at its end)
WORK_DIR = "encore"
STEP_KEYS = {"20": "engine.preparing", "19": "engine.preparing", "25": "engine.generating", "26": "engine.saving",
             "27": "engine.decoding", "28": "engine.preview"}
ACTIVE = ("queued", "running")


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
                             "studio": {k: st.get(k) for k in ("branch", "portion", "predecessor", "extra_loras", "upscale", "line")
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
        self.wake.set()
        return self.list_jobs(name)

    def generate(self, name, clip_index, after=None, plan_from=None, entry=None, seed=None, branch=None, loras=None,
                 upscale_settings=None, edit_instruction=None, line=False):
        """A new take of clip clip_index (chantier A).
        after: the take of the previous clip it follows (a take, or the take id of a generation still waiting);
        None for clip 1. plan_from: the leaf of the twig whose plan gives the clip (when entry is None) and the
        suite of the new take; by default the twig ending with `after` (« clip suivant »), or the master plan.
        entry: the clip as set in the launch panel. seed: None = random. loras / upscale_settings: None = the
        branch's. edit_instruction: None = that of the plan. line: a cell of the master line (0.48): the clip of the
        master plan, after the take of the line for the clip before (entry, plan_from and after are not used)."""
        with self.launch_lock:
            return self._generate(name, int(clip_index), (after or "").strip() or None, (plan_from or "").strip() or None,
                                  entry, None if seed in (None, "") else int(seed), branch or None, loras,
                                  upscale_settings, edit_instruction, line=bool(line))

    # ------------------------------------------------------------------ ▶▶ compléter: the rest of a twig's plan
    def fill_twig(self, name, branch_id, leaf=None, dry_run=True, assemble=True):
        """Generates the clips of a twig's plan that have no take yet, each one after the one before, with a random
        seed. Without a leaf: the empty cells of the branch's master line (0.48); the selection ending with the last
        take of the master line (and no plan of its own) is the master line too. dry_run: only says what would be
        generated."""
        with self.launch_lock:
            path = self._project(name)
            branch = projects.find_branch(projects.read_meta(path)["branches"], branch_id)
            with self.lock:
                self._load(name)       # generations already queued on the branch do not block: the twig goes through them
            pending = self._pending_takes(name)
            line = plans.line_of(path, branch_id, pending=pending)
            end = plans.line_end(line)
            on_line = not leaf or (leaf == line.get(end) and plans.suite(path, leaf) is None)
            if on_line:
                twig = plans.plan_of(path, branch_id, None, pending=pending, project_name=name)
                twig = dict(twig, locked=end, chain=[line[i] for i in range(1, end + 1)])
                leaf = line.get(end)
            else:
                twig = plans.plan_of(path, branch_id, leaf, pending=pending, project_name=name)
            plan_raw = twig["plan"]
            errors, _w = plan_core.validate(json.loads(json.dumps(plan_raw)))
            if errors:
                raise StudioError(_t("engine.the_plan_has_error_s", v0=len(errors), v1=errors[0]))
            plan = plan_core.normalize(json.loads(json.dumps(plan_raw)))
            settings = projects.read_project(self.studio.root, name)["settings"]
            steps = int(settings.get("steps") or 8)
            w, h = branch.get("width") or 960, branch.get("height") or 544
            items, total, known = [], 0.0, True
            skip = set(line) if on_line else set()        # 0.49: the clips taken over after clips left free
            for clip in plan["clips"][(0 if on_line else twig["locked"]):]:
                if (on_line and (clip["index"] <= end or clip["index"] in skip)):
                    continue
                estimate = self._total_estimate({"units": int(w) * int(h) * int(clip["frames"]) / 1e6, "steps": steps,
                                                 "upscale": bool(projects.upscale_of(branch).get("enabled"))})
                if estimate is None:
                    known = False
                else:
                    total += estimate
                items.append({"clip": clip["index"], "name": clip.get("name") or "", "frames": clip["frames"],
                              "new_scene": not (clip["continue"] and clip["index"] > 1)})
            todo = {"branch": branch_id, "branch_name": branch["name"], "leaf": leaf, "items": items, "line": on_line,
                    "eta": round(total) if items and known else None}
            if dry_run or not items:
                return todo
            lot = uuid.uuid4().hex[:10]
            label = _t("engine.fill_label", branch=branch["name"], s="s" if len(items) > 1 else "",
                       clips=_ranges([i["clip"] for i in items])) + (_t("engine.assembly") if assemble else "")
            # a duplicated branch without its own take yet: after the last clip it takes over
            launched, made, previous = [], {}, leaf or (twig["chain"][-1] if twig["chain"] else None)
            for item in items:
                if on_line and item["clip"] - 1 in line and item["clip"] - 1 not in made:
                    previous = line[item["clip"] - 1]     # after a portion taken over
                job = self._generate(name, item["clip"], previous, None if on_line else previous, None, None, branch_id, None,
                                     None, None, lot=lot, lot_label=label, line=on_line)
                launched.append(job["id"])
                made[item["clip"]] = job["take_id"]
                previous = job["take_id"]
            assembly = None
            if assemble:
                last = previous
                if on_line:         # 0.49: the line goes on with the clips taken over after the last one generated
                    k = items[-1]["clip"] + 1
                    while k in line:
                        last, k = line[k], k + 1
                assembly = self._assemble_twig(name, last, lot=lot, lot_label=label, branch_id=branch_id)
            return dict(todo, launched=launched, assembly=assembly["id"] if assembly else None)

    def project_busy(self, name):
        """Number of generations or assemblies of a project still waiting or running."""
        with self.lock:
            self._load(name)
            return sum(1 for j in self.jobs.values() if j.get("project") == name and (j["status"] in ACTIVE or j["status"] == "harvest"))

    def forget_project(self, name):
        """A deleted project: its finished jobs leave the list (none is waiting: see project_busy)."""
        with self.lock:
            for jid in [i for i, j in self.jobs.items() if j.get("project") == name]:
                self.jobs.pop(jid, None)
                if jid in self.order:
                    self.order.remove(jid)
            self.loaded.discard(name)
            self._save_queue()

    def files_waiting(self, name):
        """The project files the generations still waiting or running will send (they must not be deleted)."""
        out = set()
        with self.lock:
            for job in self.jobs.values():
                if job.get("project") != name or job["status"] not in ACTIVE:
                    continue
                spec = job.get("spec") or {}
                for files in (spec.get("files") or {}).values():
                    out.update(v for k, v in (files or {}).items() if v and not k.endswith("_sha"))
                for key in ("song",):
                    if spec.get(key):
                        out.add(spec[key])
        return out

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
    def assemble(self, name, clip=None, take_id=None, job_id=None, branch=None):
        """Assembles the twig ending with take_id (or with the take a waiting generation will make). branch: the
        branch that takes over take_id, when it is a clip taken over (0.49)."""
        with self.launch_lock:
            if job_id:
                with self.lock:
                    self._load(name)
                    job = self.jobs.get(str(job_id))
                if not job or job["project"] != name or job["kind"] != "clip" or job["status"] not in ACTIVE:
                    raise StudioError(_t("engine.this_generation_is_no_longer_waiting"))
                return self._assemble_twig(name, job["take_id"], lot=job.get("lot"), lot_label=job.get("lot_label"))
            return self._assemble_twig(name, str(take_id or ""), branch_id=branch or None)

    def _assemble_twig(self, name, leaf_id, lot=None, lot_label=None, branch_id=None):
        """The assembly of the clips 1..k of a twig. Takes still to come (generations waiting) are given when they
        are harvested. The plan sent is the plan of the twig as its takes were made."""
        path = self._project(name)
        project = projects.read_project(self.studio.root, name)
        pending = self._pending_takes(name)
        known = plans.records_by_id(path)
        if leaf_id not in known and leaf_id not in pending:
            raise StudioError(_t("engine.take_no_longer_exists", leaf_id=leaf_id))
        leaf_record = known[leaf_id][1] if leaf_id in known else pending[leaf_id][1]
        # branch_id: a clip taken over is assembled in the branch that takes it over (its leaf is not its own)
        if not branch_id or leaf_id not in plans.kept_of(path, branch_id).values():
            branch_id = takes.take_branch(leaf_record, None)
        branch = projects.find_branch(project["branches"], branch_id)
        twig = plans.plan_of(path, branch_id, leaf_id, known, pending, project_name=name)
        count = len(twig["chain"]) if leaf_id in plans.kept_of(path, branch_id).values() else twig["locked"]
        raw = dict(twig["plan"], clips=twig["plan"]["clips"][:count])
        plan = plan_core.normalize(json.loads(json.dumps(raw)))
        steps = {int(i): t for i, t in twig["takes"].items() if int(i) <= count}
        chosen = {i: t for i, t in steps.items() if t in known}
        waiting = {i: pending[t][1]["job"] for i, t in steps.items() if t not in known}
        return self._make_assembly(name, path, raw, plan, project["settings"], branch, chosen, count, leaf=leaf_id,
                                   pending=waiting, wait_for=list(waiting.values()), lot=lot, lot_label=lot_label)

    def _make_assembly(self, name, path, raw, plan, settings, branch, chosen, count, leaf=None, pending=None,
                       wait_for=None, lot=None, lot_label=None):
        """The assembly job of clips 1..count. chosen: {clip: take id} for takes that exist; pending: {clip: job id}
        for takes still to generate (resolved when they are harvested). raw: the plan of the twig."""
        branch_id = branch["id"]
        free = plan["mode"] == "free"
        with self.lock:
            self._load(name)
            waiting = {j.get("export") for j in self.jobs.values() if j["project"] == name and j.get("kind") == "assemble"
                       and j["status"] in ACTIVE + ("harvest",)}
        export = export_name(path, name, branch["name"], taken=waiting)
        # 0.50: Encore assembles itself with ffmpeg, from the takes' previews (assembler.py): ComfyUI is not needed
        start = plan.get("start_video") if (plan.get("start_video") or {}).get("in_assembly") else None
        edit = plan.get("edit_video") if (plan.get("edit_video") or {}).get("sound") == "original" else None
        start_video = None
        if start:                                     # the segment opens the video: the project's start video
            rel = projects.video_file(path, plan)
            video_file = projects.safe_join(path, rel or "")
            if not rel or not video_file.is_file():
                raise StudioError(_t("engine.start_video_not_chosen"))
            start_video = {"name": start["ref"], "video": rel, "sha": takes.file_sha(video_file)}
        edit_video = None
        if edit:                                      # the final video keeps the edited video's sound
            rel = projects.video_file(path, plan)
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
               "leaf": leaf,
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
                  edit_instruction, lot=None, lot_label=None, line=False):
        path = self._project(name)
        project = projects.read_project(self.studio.root, name)
        settings, branches = project["settings"], project["branches"]
        if any(l.get("enabled") and not l.get("name") for l in settings.get("loras") or []):
            raise StudioError(_t("engine.an_active_lora_has_no_file"))
        known = plans.records_by_id(path)
        pending = self._pending_takes(name)
        if line:
            # a cell of the master line: generated once, in order, after the take of the line for the clip before
            if not branch_id:
                raise StudioError(_t("engine.no_branch_create_one_with_new"))
            cells = plans.line_of(path, branch_id, known, pending)
            if index in cells:
                raise StudioError(_t("engine.line_cell_done", index=index))
            if index != plans.line_end(cells) + 1:
                raise StudioError(_t("engine.line_cell_order", index=index, before=plans.line_end(cells) + 1))
            after, plan_from, entry = cells.get(index - 1), None, None

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
            if not branch_id or after not in plans.kept_of(path, branch_id).values():
                branch_id = takes.take_branch(after_record, branch_id)
            elif plans.holes_of(path, branch_id):
                # 0.49: after a clip taken over that follows a clip left free, that clip must have a take here first
                plans.chain(path, after, known, pending, plans.selection_prefer(path, branch_id), branch=branch_id)
        if not branch_id:
            raise StudioError(_t("engine.no_branch_create_one_with_new"))
        branch = projects.find_branch(branches, branch_id)
        # (0.48.2) a clip the branch takes over from another one can get a take of its own: a variant in this branch,
        # after the clip taken over before it; the branch it comes from does not change

        # the plan: the twig before (portions), this clip, then the suite of the twig it is taken from (the master
        # plan for the master line)
        source = plans.plan_of(path, branch_id, None if line else (plan_from or after), known, pending, project_name=name)
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
        kept = plans.kept_of(path, branch_id)
        if plans.holes_of(path, branch_id) and index < max(kept):
            # 0.49: before a portion taken over, the clips keep their length (the portion stays at its moment)
            want = ((plans.plan_of(path, branch_id, None, known, pending)["plan"]["clips"] or [])[index - 1] or {}).get("frames")
            if want is not None and int(entry.get("frames") or 0) != int(want):
                raise StudioError(_t("engine.portion_frames_locked", index=index, frames=int(want)))
        before = plans.plan_of(path, branch_id, after, known, pending, project_name=name)["plan"] if after else {"clips": []}
        composed = plans.head(src)
        if edit_instruction is not None and isinstance(composed.get("edit_video"), dict):
            composed["edit_video"]["instruction"] = str(edit_instruction)
            if isinstance(entry.get("defs"), dict):
                entry["defs"].pop("edit_instruction", None)
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
        refs, problems = clip_needs(plan, index, {"video": projects.video_file(path, plan), "song": branch.get("song") or ""})
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
                                video=any(r.get("video") for r in refs), voices=free and any(r.get("voice") for r in refs),
                                continues=bool(clip["continue"] and index > 1))
        if missing:
            raise StudioError(_t("engine.nodes_missing_from_comfyui") + ", ".join(missing)
                              + (_t("engine.kjnodes_preview_install_comfyui_kjnodes_or")
                                 if "ModelPreviewOverrideKJ" in missing else "")
                              + (_t("engine.multiref_needed") if any(n.startswith("MiniMaxH3") and n not in
                                 ("MiniMaxH3SigmaShift", "MiniMaxH3ReferenceToVideo") for n in missing) else ""))
        if clip["continue"] and index > 1 and after in known and not takes.latent_ok(path, index - 1, after):
            raise StudioError(_t("engine.take_cannot_be_continued", take=after))
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
            "portion": {"clip": dict(entry, defs=plan_core.snapshot_defs(raw, plan, index))},
            "predecessor": after,
            "raw_start": plan_core.timeline(plan)[index - 1]["raw_start"],
            **({"line": True} if line else {}),
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
        # the master plan of the branch no longer changes (a clip of the master line freezes that clip and its subjects)
        plans.freeze(path, branch_id, index if line else None,
                     (studio_info["portion"]["clip"].get("defs") or {}).get("subjects") or {} if line else (), known, pending)
        # what comes after the new take: the suite of the twig it was taken from (its clips after this one); after a
        # take of the master line comes the master plan itself
        if not line:
            plans.set_suite(path, take_id, index, plans.suite_from(raw, index))
        with self.lock:
            self.jobs[job["id"]] = job
            self._enqueue(job)
            self._save(name)
        self.wake.set()
        return self._public(job)

    # ------------------------------------------------------------------ sending a job to ComfyUI
    def _dispatch_clip(self, client, job):
        """Prepares and sends what a frozen generation needs (pictures, voices, song, the video or the take it
        continues), builds its workflow and queues it (0.50: ComfyUI's own nodes, MultiRef and VHS)."""
        name, spec = job["project"], job["spec"]
        path, raw, index = self._project(name), spec["raw"], job["clip"]
        studio = job.get("studio") or {}
        width, height = int(studio.get("width") or spec["settings"]["width"]), int(studio.get("height") or spec["settings"]["height"])
        ffmpeg = previews.find_ffmpeg(self.studio.config)
        sent = dict(json.loads(json.dumps(raw)), project=name, version=plan_core.PLAN_VERSION,
                    ref_image_size=studio.get("ref_image_size") or projects.DEFAULT_REF_SIZE)
        try:
            plan = plan_core.normalize(sent)
        except plan_core.PlanError as exc:
            raise StudioError(_t("engine.the_plan_has_error_s", v0=len(exc.errors), v1=exc.errors[0])) from exc
        entry, row = plan["clips"][index - 1], plan_core.timeline(plan)[index - 1]
        free = plan["mode"] == "free"
        # the project files, unchanged since the launch
        local = {}
        for ref_name in spec["refs"]:
            f = spec["files"].get(ref_name) or {}
            for kind in ("image", "voice", "video"):
                if f.get(kind):
                    local_file = projects.safe_join(path, f[kind])
                    if not local_file.is_file() or takes.file_sha(local_file) != f.get(kind + "_sha"):
                        raise StudioError(_t("engine.the_file_of_has_changed_or", ref_name=ref_name, v1=f[kind]))
                    local[(ref_name, kind)] = (local_file, f[kind + "_sha"])
        has_image = {n for (n, kind) in local if kind == "image"}
        has_voice = {n for (n, kind) in local if kind == "voice"} if free else set()
        edit_spec = plan.get("edit_video") if plan_core.edit_slice(plan, index) else None
        edit_sound = False
        if edit_spec:
            if (edit_spec["ref"], "video") not in local:
                raise StudioError(_t("engine.edit_video_not_chosen"))
            prepare.need_ffmpeg(ffmpeg, _t("prepare.what_video"))
            edit_sound = prepare.probe(ffmpeg, local[(edit_spec["ref"], "video")][0])[1]
        # the prompt composed by Encore, its pictures and voices in the order of <Picture i> / <Audio j>
        try:
            prompt, image_names, voice_names, notes = plan_core.resolve_prompt(
                entry["prompt"], entry["refs"], has_image, has_voice, use_voices=free, audio_offset=1 if edit_sound else 0)
        except plan_core.PlanError as exc:
            raise StudioError("; ".join(exc.errors)) from exc
        if len(image_names) > plan_core.MAX_REFS or len(voice_names) > plan_core.MAX_VOICES \
                or len(image_names) + len(voice_names) > plan_core.MAX_REF_FILES:
            raise StudioError(_t("engine.too_many_refs", index=index, images=len(image_names), voices=len(voice_names)))
        here = f"{WORK_DIR}/{name}"
        root_prefix = f"{WORK_DIR}_{name}_"
        images = [self._send_input(client, *local[(n, "image")], here, job=job) for n in image_names]
        cut, more = prepare.voices(ffmpeg, path, [(n, *local[(n, "voice")]) for n in voice_names])
        notes += more
        voices = [self._send_input(client, f, takes.file_sha(f), "", prefix=root_prefix, job=job) for f in cut]
        song = None
        if not free:
            song_file = projects.safe_join(path, spec["song"] or "")
            if not song_file.is_file() or takes.file_sha(song_file) != spec.get("song_sha"):
                raise StudioError(_t("engine.the_song_has_changed_or_disappeared", v0=spec["song"]))
            shifted = prepare.shifted_song(ffmpeg, path, song_file, spec["song_sha"], plan_core.song_offset(plan))
            song = self._send_input(client, shifted, takes.file_sha(shifted), "", prefix=root_prefix, job=job)
        # what it continues: the end of the start video (clip 1), or the take before it
        source, parent = None, None
        start_spec = plan.get("start_video")
        if index == 1 and entry["continue"] and start_spec:
            if (start_spec["ref"], "video") not in local:
                raise StudioError(_t("engine.start_video_not_chosen"))
            frames = min(int(start_spec["frames"]), prepare.START_CONTEXT_SOURCE)
            piece = prepare.video_piece(ffmpeg, path, *local[(start_spec["ref"], "video")], int(start_spec["end_frame"]) - frames,
                                        frames, width, height, sound=True)
            source = {"video": self._send_input(client, piece, takes.file_sha(piece), "", prefix=root_prefix, job=job)}
        elif entry["continue"] and index > 1:
            parent = spec.get("parent_take") or self._parent_of(path, job)
            source = {"latent": self._send_latent(client, path, name, index - 1, parent, job)}
        edit = None
        if edit_spec:
            first, count = plan_core.edit_slice(plan, index)
            piece = prepare.video_piece(ffmpeg, path, *local[(edit_spec["ref"], "video")], first, count, width, height, sound=edit_sound)
            edit = {"video": self._send_input(client, piece, takes.file_sha(piece), "", prefix=root_prefix, job=job), "sound": edit_sound}
        try:
            info = self._object_info()
        except comfy.ComfyError as exc:
            raise StudioError(str(exc)) from exc
        take_id = job["take_id"]
        save_prefix = f"{here}/takes/{take_id}"
        workflow = clip_workflow({
            "settings": spec["settings"], "mode": spec["mode"], "prompt": prompt, "length": int(entry["frames"]),
            "ref_image_size": plan.get("ref_image_size"), "seed": job["seed"], "images": images, "voices": voices,
            "song": song, "clip_start": row["raw_start_seconds"], "context": int(row["context"]),
            "feather": int(plan.get("audio_feather_ticks", 8)), "source": source, "edit": edit,
            "save_prefix": save_prefix, "preview_prefix": f"{here}/previews/{take_id}", "names": ref_inputs(info),
            "upscale": spec.get("upscale"), "context_latent": spec.get("context_latent") or 0,
        })
        missing = sorted({n["class_type"] for n in workflow.values() if n["class_type"] not in info})
        if missing:
            raise StudioError(_t("engine.nodes_missing_from_comfyui") + ", ".join(missing))
        with self.lock:
            job.update(save_prefix=save_prefix, notes=notes, fingerprint=plan_core.take_fingerprint(plan, index),
                       clip_name=entry.get("name") or "", parent=parent if source and source.get("latent") else None)
        return client.queue_prompt(workflow, self.client_id, {"project": name, "clip": index, "token": job["token"]})

    def _parent_of(self, path, job):
        """The take a generation continues when it was launched after a generation then still waiting (its take is
        known now: _ready waited for it)."""
        token = job.get("parentToken")
        local = takes.list_takes(path).get(job["clip"] - 1, [])
        record = next((r for r in local if token and r["id"].endswith("_" + token)), None)
        if record is None:
            raise StudioError(_t("engine.the_take_of_clip_this_clip", v0=job["clip"] - 1))
        return record["id"]

    def _send_latent(self, client, path, name, index, take_id, job):
        """The latent of the take a generation continues, into ComfyUI's output folder (MultiRef's loader reads it
        there), sent once per ComfyUI; returns its path from the output folder."""
        if not take_id or not takes.latent_ok(path, index, take_id):
            raise StudioError(_t("engine.take_cannot_be_continued", take=take_id or "?"))
        file = takes.take_files(path, index, take_id)[0]
        sub = f"{WORK_DIR}/{name}/latents"
        key = (self.studio.config["comfy_url"], sub, take_id)
        if key not in self.uploaded:
            def progress(sent, total):
                if total > 8 * 1024 * 1024:
                    job["step"] = _t("engine.sending_to_comfyui", file=file.name, v1=int(100 * sent / total))
            self._put(client, file, file.name, sub, "output", progress)
            self.uploaded[key] = True
        return f"{sub}/{file.name}"

    def _resolve_assembly(self, job):
        """The takes of a planned assembly (generations it waited for), known only now."""
        for clip_key, jid in list((job.get("pending") or {}).items()):
            other = self.jobs.get(jid)
            if not other or not other.get("take"):
                raise StudioError(_t("engine.the_take_of_clip_does_not", clip_key=clip_key))
            job["takes"][clip_key] = other["take"]

    def _local_assemblies(self):
        """Assemblies Encore makes itself with ffmpeg from the takes' previews, beside ComfyUI's work (one at a
        time). One that cannot (no ffmpeg, a take without preview) fails with the reason (0.50: no other way)."""
        self._sweep_orphans()
        with self.lock:
            if self.paused or any(j.get("local") and j["status"] == "running" for j in self.jobs.values()):
                return
            job = next((self.jobs[i] for i in self.order if i in self.jobs and self.jobs[i]["kind"] == "assemble"
                        and self._ready(self.jobs[i])), None)
            if job is None:
                return
            try:
                self._resolve_assembly(job)
            except (StudioError, OSError, ValueError) as exc:
                return self._fail(job, str(exc))
            path = self._project(job["project"])
            ffmpeg, why = assembler.ready_for(path, job, self.studio.config)
            if ffmpeg is None:
                return self._fail(job, why)
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
                "assembled_by": "ffmpeg"}
        meta = path / "exports" / f"{job['export']}.json"
        tmp = meta.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, meta)
        try:
            write_infos(path, job, report)
        except Exception as exc:          # never lose a video because of its information file
            print(_t("engine.encore_infos_of_not_written", v0=job['export'], exc=exc), flush=True)

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
                            and self.jobs[i]["kind"] != "assemble"), None)
                if job is None:
                    return
            client = self.client
            self._ensure_socket()
            try:
                answer = self._dispatch_clip(client, job)
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
                traceback.print_exc()
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
        for name in {n for n, _b in touched}:
            self._purge_if_idle(client, name)

    def _harvest(self, client, job):
        """A generation over: its latent (MultiRef's file) and its preview (VHS) come into the project, with the
        record Encore writes (0.50: the plugin wrote it before)."""
        name, branch = job["project"], _branch(job)
        try:
            path = self._project(name)
            take_id = job["take_id"]
            entry = client.history(job["prompt_id"]).get(job["prompt_id"]) or {}
            st, meta, mp4 = takes.take_files(path, job["clip"], take_id)
            st.parent.mkdir(parents=True, exist_ok=True)
            sub, file_name = saved_latent_name(job.get("save_prefix") or f"{WORK_DIR}/{name}/takes/{take_id}")
            part = st.with_suffix(".part")
            client.download(file_name, sub, str(part))
            latents.check_av(part)
            os.replace(part, st)
            out = (entry.get("outputs") or {}).get("28") or {}
            videos = [f for f in (out.get("gifs") or out.get("videos") or []) if str(f.get("filename", "")).lower().endswith(".mp4")]
            if videos:
                client.download(videos[-1]["filename"], videos[-1].get("subfolder", ""), str(mp4), videos[-1].get("type", "output"))
            studio = job.get("studio") or {}
            record = {"clip": job["clip"], "name": job.get("clip_name") or "", "seed": job.get("seed"), "saved_at": time.time(),
                      "fingerprint": job.get("fingerprint"), "frames": job.get("frames"), "width": studio.get("width"),
                      "height": studio.get("height"), "refs": studio.get("refs") or {}, "parent": job.get("parent"),
                      "notes": job.get("notes") or [],
                      "studio": dict(studio, prompt_id=job.get("prompt_id"))}
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

    def _purge_if_idle(self, client, name, branch=None):
        """When no generation of the project is waiting any more, what it left in ComfyUI's output folder (its takes,
        previews and the latents sent to be continued) is removed: they are in the project. Only when ComfyUI's
        folder is known (welcome screen): ComfyUI has no route to delete files, so with a ComfyUI elsewhere they
        stay (the project settings say so)."""
        if not self.studio.config.get("purge_comfy_copy", True):
            return
        root = comfy_setup.comfy_root(self.studio.config.get("comfy_dir"))
        if root is None:
            return
        with self.launch_lock:
            with self.lock:
                mine = [j for j in self.jobs.values() if j["project"] == name]
                if any(j["status"] in ACTIVE + ("harvest",) for j in mine):
                    return
                # takes whose copy into the project failed are kept (their files can still be fetched by hand)
                keep = {j["take_id"] for j in mine if j.get("harvest_tries") and j.get("take_id")}
            folder = root / "output" / WORK_DIR / name
            for kind in ("takes", "previews", "latents"):
                for file in (folder / kind).glob("*") if (folder / kind).is_dir() else []:
                    if file.is_file() and not any(file.name.startswith(t) for t in keep):
                        try:
                            file.unlink()
                        except OSError:
                            pass
            url = self.studio.config.get("comfy_url")
            for key in [k for k in self.uploaded if k[0] == url and k[1] == f"{WORK_DIR}/{name}/latents"]:
                self.uploaded.pop(key, None)


def _branch(job):
    return job.get("branch") or "b1"     # generations started before branches existed
