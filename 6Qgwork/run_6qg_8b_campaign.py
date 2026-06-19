#!/usr/bin/env python3
"""Run parallel 6Qg -> forced 8b production campaigns."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
from pathlib import Path
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = Path(__file__).resolve().parent
CAMPAIGNS_DIR = WORK_DIR / "campaigns"
DEFAULT_TEMPLATE = WORK_DIR / "input_6b1g_lhapdf_example3"
DEFAULT_HERWIG_TEMPLATE = WORK_DIR / "AlpGen8Q-LHEWriter.in"
DEFAULT_ALPGEN = WORK_DIR / "6Qggen"
DEFAULT_ALPGENTOLH = REPO_ROOT / "alpgentolh" / "AlpGenToLH"
DEFAULT_REWEIGHT = (
    REPO_ROOT
    / "herwig-min-b-shower-veto"
    / "scripts"
    / "apply_lhe_prob_weights.py"
)
STAGE_SEQUENCE = [
    "setup",
    "alpgen_mode1",
    "alpgen_mode2",
    "alpgentolh",
    "herwig_prepare",
    "herwig_read",
    "herwig_run",
    "reweight",
    "validate",
    "complete",
]
STAGE_LABELS = {
    "pending": "pending",
    "setup": "setup",
    "alpgen_mode1": "AlpGen mode 1",
    "alpgen_mode2": "AlpGen mode 2",
    "alpgentolh": "AlpGenToLH",
    "herwig_prepare": "prepare Herwig input",
    "herwig_read": "Herwig read",
    "herwig_run": "Herwig run",
    "reweight": "apply p_hat weights",
    "validate": "validate final LHE",
    "complete": "complete",
    "failed": "failed",
}
STAGE_INDEX = {stage: index for index, stage in enumerate(STAGE_SEQUENCE)}
RUN_UNITS = len(STAGE_SEQUENCE) - 1
SUCCESS_STATUSES = {"success", "success_partial"}
TERMINAL_STATUSES = SUCCESS_STATUSES | {"failed"}


class RunError(RuntimeError):
    pass


class ProgressMonitor:
    def __init__(
        self,
        run_indices: list[int],
        tag_prefix: str,
        interval: float,
        campaign_dir: Path | None = None,
        alpgen_workload: dict[str, Any] | None = None,
        alpgen_poll_interval: float = 5.0,
        stream=sys.stderr,
    ) -> None:
        self.queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.interval = interval
        self.campaign_dir = campaign_dir
        self.alpgen_workload = alpgen_workload
        self.alpgen_poll_interval = alpgen_poll_interval
        self.stream = stream
        self.start_time = time.time()
        self.states: dict[int, dict[str, Any]] = {
            run_index: {
                "tag": f"{tag_prefix}_r{run_index:06d}",
                "stage": "pending",
                "status": "pending",
                "events": None,
                "error": None,
                "alpgen_progress": None,
                "alpgen_started_at": None,
            }
            for run_index in run_indices
        }
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()
        self.render_summary(force=True)

    def stop(self) -> None:
        self.queue.put({"type": "stop"})
        self._thread.join()
        self.render_summary(force=True)

    def _loop(self) -> None:
        next_summary = time.time() + self.interval
        next_alpgen_poll = time.time() + min(1.0, self.alpgen_poll_interval)
        while True:
            timeout = max(0.1, min(next_summary, next_alpgen_poll) - time.time())
            try:
                event = self.queue.get(timeout=timeout)
            except queue.Empty:
                now = time.time()
                if now >= next_alpgen_poll:
                    self.poll_alpgen_progress()
                    next_alpgen_poll = now + self.alpgen_poll_interval
                if now >= next_summary:
                    self.render_summary()
                    next_summary = now + self.interval
                continue

            if event.get("type") == "stop":
                break
            self.apply_event(event)
            self.render_event(event)
            now = time.time()
            if now >= next_alpgen_poll:
                self.poll_alpgen_progress()
                next_alpgen_poll = now + self.alpgen_poll_interval
            if now >= next_summary:
                self.render_summary()
                next_summary = now + self.interval

    def apply_event(self, event: dict[str, Any]) -> None:
        run_index = event["run_index"]
        state = self.states.setdefault(
            run_index,
            {
                "tag": event["tag"],
                "stage": "pending",
                "status": "pending",
                "events": None,
                "error": None,
                "alpgen_progress": None,
                "alpgen_started_at": None,
            },
        )
        previous_stage = state["stage"]
        state["tag"] = event["tag"]
        state["stage"] = event["stage"]
        state["status"] = event["status"]
        if state["stage"] == "alpgen_mode1" and previous_stage != "alpgen_mode1":
            state["alpgen_started_at"] = event["timestamp"]
            state["alpgen_progress"] = None
        elif state["stage"] != "alpgen_mode1":
            state["alpgen_progress"] = None
            state["alpgen_started_at"] = None
        if "events" in event:
            state["events"] = event["events"]
        if "error" in event:
            state["error"] = event["error"]

    def completed_units(self) -> float:
        total = 0.0
        for state in self.states.values():
            stage = state["stage"]
            if state["status"] in TERMINAL_STATUSES:
                total += RUN_UNITS
            else:
                total += STAGE_INDEX.get(stage, 0)
                if stage == "alpgen_mode1" and state.get("alpgen_progress"):
                    total += state["alpgen_progress"]["fraction"]
        return total

    def format_eta(self) -> str:
        total_units = len(self.states) * RUN_UNITS
        completed = self.completed_units()
        if completed <= 0:
            return "unknown"
        elapsed = time.time() - self.start_time
        remaining = max(0, total_units - completed)
        eta_seconds = remaining / (completed / elapsed)
        return format_duration(eta_seconds)

    def render_event(self, event: dict[str, Any]) -> None:
        label = STAGE_LABELS.get(event["stage"], event["stage"])
        message = event.get("message", "")
        suffix = f" - {message}" if message else ""
        if event["status"] in SUCCESS_STATUSES:
            suffix += f" events={event.get('events')}"
        if event["status"] == "failed":
            suffix += f" error={event.get('error')}"
        print(f"[stage] {event['tag']}: {label}{suffix}", file=self.stream, flush=True)

    def render_summary(self, force: bool = False) -> None:
        total_runs = len(self.states)
        done = sum(1 for state in self.states.values() if state["status"] in SUCCESS_STATUSES)
        partial = sum(1 for state in self.states.values() if state["status"] == "success_partial")
        failed = sum(1 for state in self.states.values() if state["status"] == "failed")
        total_units = total_runs * RUN_UNITS
        completed_units = self.completed_units()
        active = []
        for state in self.states.values():
            if state["status"] != "running":
                continue
            active.append(self.active_text(state))
        elapsed = format_duration(time.time() - self.start_time)
        print(
            "[progress] "
            f"runs {done}/{total_runs} complete"
            + (f", {partial} partial" if partial else "")
            + f", {failed} failed; "
            f"stages {completed_units:.1f}/{total_units}; elapsed {elapsed}; "
            f"ETA {self.format_eta()}",
            file=self.stream,
            flush=True,
        )
        if active or force:
            active_text = ", ".join(active[:12])
            if len(active) > 12:
                active_text += f", ... +{len(active) - 12} more"
            print(
                f"[progress] active: {active_text if active_text else 'none'}",
                file=self.stream,
                flush=True,
            )

    def active_text(self, state: dict[str, Any]) -> str:
        label = STAGE_LABELS.get(state["stage"], state["stage"])
        progress = state.get("alpgen_progress")
        if state["stage"] == "alpgen_mode1" and progress:
            label = (
                f"{label} {progress['label']} "
                f"{progress['percent']:.1f}% ETA {progress['eta']}"
            )
        return f"{state['tag']}:{label}"

    def poll_alpgen_progress(self) -> None:
        if not self.campaign_dir or not self.alpgen_workload:
            return
        for run_index, state in self.states.items():
            if state["status"] != "running" or state["stage"] != "alpgen_mode1":
                continue
            tag = state["tag"]
            run_dir = self.campaign_dir / f"run_{run_index:06d}"
            progress = read_alpgen_mode1_progress(
                run_dir,
                tag,
                self.alpgen_workload,
                state.get("alpgen_started_at") or self.start_time,
                state.get("alpgen_progress"),
            )
            if not progress:
                continue
            previous = state.get("alpgen_progress")
            state["alpgen_progress"] = progress
            if should_render_alpgen_progress(previous, progress):
                self.render_alpgen_progress(tag, progress)

    def render_alpgen_progress(self, tag: str, progress: dict[str, Any]) -> None:
        print(
            "[alpgen] "
            f"{tag}: {progress['label']} "
            f"{format_count(progress['current_done'])}/{format_count(progress['current_target'])}; "
            f"total {format_count(progress['done'])}/{format_count(progress['total'])} "
            f"({progress['percent']:.1f}%); "
            f"rate {format_count(progress['rate'])}/s; ETA {progress['eta']}",
            file=self.stream,
            flush=True,
        )


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_count(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}k"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def fortran_float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def tokens_before_comment(line: str) -> list[str]:
    return line.split("!", 1)[0].split()


def parse_mode1_workload(input_path: Path) -> dict[str, Any]:
    lines = input_path.read_text().splitlines()
    if len(lines) < 5:
        raise ValueError(f"AlpGen input is missing mandatory lines: {input_path}")

    opt_tokens = tokens_before_comment(lines[3])
    gen_tokens = tokens_before_comment(lines[4])
    if len(opt_tokens) < 2 or not gen_tokens:
        raise ValueError(f"Could not parse AlpGen mode-1 event counts from {input_path}")

    nopt = int(fortran_float(opt_tokens[0]))
    niter = int(fortran_float(opt_tokens[1]))
    generated_events = int(fortran_float(gen_tokens[0]))
    passes: list[dict[str, Any]] = []
    if nopt > 0 and niter > 0:
        for index in range(niter):
            passes.append(
                {
                    "label": f"warmup {index + 1}/{niter}",
                    "events": nopt,
                }
            )
    passes.append({"label": "weighted generation", "events": generated_events})

    return {
        "nopt": nopt,
        "niter": niter,
        "generated_events": generated_events,
        "passes": passes,
        "total_events": sum(int(item["events"]) for item in passes),
    }


def parse_alpgen_processed(mon_path: Path) -> int | None:
    if not mon_path.exists():
        return None
    pattern = re.compile(r"processed=\s*([0-9.+\-EeDd]+)\s+events")
    for line in mon_path.read_text(errors="replace").splitlines():
        match = pattern.search(line)
        if match:
            return int(fortran_float(match.group(1)))
    return None


def parse_alpgen_pass_index_from_text(path: Path, workload: dict[str, Any]) -> int | None:
    if not path.exists():
        return None
    pattern = re.compile(r"starting generation of\s+([0-9.+\-EeDd]+)\s+events")
    starts = pattern.findall(path.read_text(errors="replace"))
    if not starts:
        return None
    return min(len(starts) - 1, len(workload["passes"]) - 1)


def read_alpgen_mode1_progress(
    run_dir: Path,
    tag: str,
    workload: dict[str, Any],
    started_at: float,
    previous: dict[str, Any] | None,
) -> dict[str, Any] | None:
    mon_path = run_dir / f"{tag}.mon"
    stat_path = run_dir / f"{tag}.stat"
    stdout_path = run_dir / f"{tag}_alpgen_mode1.stdout"
    wgt_path = run_dir / f"{tag}.wgt"
    processed = parse_alpgen_processed(mon_path)
    if processed is None:
        return None

    passes = workload["passes"]
    if wgt_path.exists() and wgt_path.stat().st_size > 0:
        pass_index = len(passes) - 1
    else:
        pass_index = parse_alpgen_pass_index_from_text(stat_path, workload)
        if pass_index is None:
            pass_index = parse_alpgen_pass_index_from_text(stdout_path, workload)
        if pass_index is None:
            pass_index = 0
        while pass_index < len(passes) - 1 and processed > int(passes[pass_index]["events"]):
            pass_index += 1
    current_target = int(passes[pass_index]["events"])
    current_done = min(max(0, processed), current_target)

    if not (wgt_path.exists() and wgt_path.stat().st_size > 0) and stat_path.exists() and mon_path.stat().st_mtime < stat_path.stat().st_mtime:
        if not previous or previous.get("pass_index") != pass_index:
            current_done = 0

    done_before = sum(int(item["events"]) for item in passes[:pass_index])
    done = min(done_before + current_done, int(workload["total_events"]))
    if previous and done < previous["done"]:
        done = previous["done"]
        current_done = min(max(0, done - done_before), current_target)

    total = int(workload["total_events"])
    elapsed = max(0.001, time.time() - started_at)
    rate = done / elapsed
    remaining = max(0, total - done)
    eta = format_duration(remaining / rate) if rate > 0 else "unknown"
    return {
        "pass_index": pass_index,
        "label": passes[pass_index]["label"],
        "current_done": current_done,
        "current_target": current_target,
        "done": done,
        "total": total,
        "fraction": done / total if total else 0.0,
        "percent": 100.0 * done / total if total else 0.0,
        "rate": rate,
        "eta": eta,
    }


def should_render_alpgen_progress(
    previous: dict[str, Any] | None,
    progress: dict[str, Any],
) -> bool:
    if previous is None:
        return True
    if progress["pass_index"] != previous["pass_index"]:
        return True
    return progress["done"] > previous["done"]


def emit_progress(
    progress_queue: queue.Queue[dict[str, Any]] | None,
    run_index: int,
    tag: str,
    stage: str,
    status: str = "running",
    message: str = "",
    events: int | None = None,
    error: str | None = None,
) -> None:
    if progress_queue is None:
        return
    event: dict[str, Any] = {
        "run_index": run_index,
        "tag": tag,
        "stage": stage,
        "status": status,
        "message": message,
        "timestamp": time.time(),
    }
    if events is not None:
        event["events"] = events
    if error is not None:
        event["error"] = error
    progress_queue.put(event)


def set_stage(
    manifest: dict[str, Any],
    progress_queue: queue.Queue[dict[str, Any]] | None,
    run_index: int,
    tag: str,
    stage: str,
    message: str = "",
) -> None:
    manifest["current_stage"] = stage
    entry = {"stage": stage, "timestamp": datetime.now().isoformat()}
    if message:
        entry["message"] = message
    manifest.setdefault("stage_history", []).append(entry)
    emit_progress(progress_queue, run_index, tag, stage, message=message)


def sanitize_tag(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        raise ValueError("tag/campaign name does not contain usable tag characters")
    return sanitized


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def seed(base: int, run_index: int, salt: int) -> int:
    return 10000 + ((base + run_index * salt) % 89999)


def set_first_token(line: str, value: str) -> str:
    comment = ""
    body = line.rstrip("\n")
    if "!" in body:
        body, comment = body.split("!", 1)
        comment = " !" + comment
    return f"{value}{comment}\n"


def set_param(lines: list[str], name: str, value: int | str) -> list[str]:
    updated: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        token = stripped.split(None, 1)[0] if stripped else ""
        if token.lower() == name.lower():
            comment = ""
            if "!" in line:
                comment = " !" + line.split("!", 1)[1].rstrip("\n")
            updated.append(f"{name} {value}{comment}\n")
            replaced = True
        else:
            updated.append(line)

    if replaced:
        return updated

    for index, line in enumerate(updated):
        stripped = line.strip().lower()
        if stripped.startswith("eoi"):
            return updated[:index] + [f"{name} {value}\n"] + updated[index:]

    return updated + [f"{name} {value}\n"]


def write_mode1_input(template: Path, output: Path, tag: str, seeds: tuple[int, int]) -> None:
    lines = template.read_text().splitlines(keepends=True)
    if len(lines) < 2:
        raise ValueError(f"AlpGen template is too short: {template}")
    lines[0] = set_first_token(lines[0], "1")
    lines[1] = set_first_token(lines[1], tag)
    lines = set_param(lines, "iseed1", seeds[0])
    lines = set_param(lines, "iseed2", seeds[1])
    output.write_text("".join(lines))


def write_mode2_input(output: Path, tag: str, seeds: tuple[int, int]) -> None:
    output.write_text(
        "\n".join(
            [
                "2         ! read weighted events for unweighting",
                f"{tag} ! string labeling input/output files",
                f"iseed3 {seeds[0]}",
                f"iseed4 {seeds[1]}",
                "eoi 1 ! end of input",
                "",
            ]
        )
    )


def replace_herwig_setting(
    lines: list[str],
    prefix: str,
    replacement: str,
) -> list[str]:
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith(prefix):
            out.append(replacement + "\n")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        raise ValueError(f"Could not find Herwig setting: {prefix}")
    return out


def write_herwig_input(
    template: Path,
    output: Path,
    input_lhe: str,
    run_basename: str,
    correction_file: str,
    number_of_events: int,
    random_seed: int,
) -> None:
    lines = template.read_text().splitlines(keepends=True)
    lines = replace_herwig_setting(
        lines,
        "set theLHReader:FileName",
        f"set theLHReader:FileName {input_lhe}",
    )
    lines = replace_herwig_setting(
        lines,
        "set theGenerator:NumberOfEvents",
        f"set theGenerator:NumberOfEvents {number_of_events}",
    )
    lines = replace_herwig_setting(
        lines,
        "set theGenerator:RandomNumberGenerator:Seed",
        f"set theGenerator:RandomNumberGenerator:Seed {random_seed}",
    )
    lines = replace_herwig_setting(
        lines,
        "set Force8BVeto:CorrectionFile",
        f"set Force8BVeto:CorrectionFile {correction_file}",
    )
    lines = replace_herwig_setting(
        lines,
        "saverun ",
        f"saverun {run_basename} theGenerator",
    )
    output.write_text("".join(lines))


def run_command(
    command: list[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    setup_command: str = "",
    check: bool = True,
) -> dict[str, Any]:
    started = time.time()
    if setup_command:
        command_text = f"{setup_command} && {shlex.join(command)}"
        exec_command: list[str] = ["bash", "-lc", command_text]
        recorded = command_text
    else:
        exec_command = command
        recorded = shlex.join(command)

    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        proc = subprocess.run(
            exec_command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            text=True,
            check=False,
        )

    finished = time.time()
    result = {
        "command": recorded,
        "cwd": rel(cwd),
        "returncode": proc.returncode,
        "stdout": rel(stdout_path),
        "stderr": rel(stderr_path),
        "elapsed_seconds": finished - started,
    }
    if proc.returncode != 0 and check:
        raise RunError(command_failure_message(result))
    return result


def command_failure_message(result: dict[str, Any]) -> str:
    return f"command failed with exit code {result['returncode']}: {result['command']}"


def run_command_with_input(
    command: list[str],
    input_path: Path,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    setup_command: str = "",
) -> dict[str, Any]:
    started = time.time()
    if setup_command:
        command_text = f"{setup_command} && {shlex.join(command)}"
        exec_command: list[str] = ["bash", "-lc", command_text]
        recorded = f"{command_text} < {input_path.name}"
    else:
        exec_command = command
        recorded = f"{shlex.join(command)} < {input_path.name}"
    with input_path.open() as stdin, stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        proc = subprocess.run(
            exec_command,
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            text=True,
            check=False,
        )
    finished = time.time()
    result = {
        "command": recorded,
        "cwd": rel(cwd),
        "returncode": proc.returncode,
        "stdout": rel(stdout_path),
        "stderr": rel(stderr_path),
        "elapsed_seconds": finished - started,
    }
    if proc.returncode != 0:
        raise RunError(f"command failed with exit code {proc.returncode}: {recorded}")
    return result


def count_lhe_events(path: Path) -> int:
    count = 0
    with path.open() as handle:
        for line in handle:
            if line.strip() == "<event>":
                count += 1
    return count


def extract_lhe_init(path: Path) -> tuple[list[str], list[str]]:
    with path.open() as handle:
        iterator = iter(handle)
        for line in iterator:
            if line.strip() == "<init>":
                return next(iterator).split(), next(iterator).split()
    raise ValueError(f"No <init> block found in {path}")


def iter_lhe_events(path: Path):
    in_event = False
    buffer: list[str] = []
    with path.open() as handle:
        for line in handle:
            stripped = line.strip()
            if stripped == "<event>":
                in_event = True
                buffer = [line]
                continue
            if in_event:
                buffer.append(line)
                if stripped == "</event>":
                    yield "".join(buffer)
                    in_event = False


def parse_lhe_event_summary(path: Path) -> dict[str, Any]:
    events = 0
    sum_weights = 0.0
    bad_final_state = 0
    with path.open() as handle:
        lines = iter(handle)
        for line in lines:
            if line.strip() != "<event>":
                continue
            header = next(lines).split()
            if len(header) < 3:
                raise ValueError(f"Malformed event header in {path}")
            nup = int(header[0])
            weight = float(header[2])
            events += 1
            sum_weights += weight
            final_b = 0
            final_g = 0
            for _ in range(nup):
                fields = next(lines).split()
                pid = int(fields[0])
                status = int(fields[1])
                if status == 1 and abs(pid) == 5:
                    final_b += 1
                if status == 1 and pid == 21:
                    final_g += 1
            if final_b != 8 or final_g != 0:
                bad_final_state += 1
    return {
        "events": events,
        "sum_weights": sum_weights,
        "bad_final_state_events": bad_final_state,
    }


def validate_lhe_declared_processes(path: Path) -> None:
    init_process_ids: set[int] = set()
    with path.open() as handle:
        lines = iter(handle)
        for line in lines:
            if line.strip() != "<init>":
                continue
            beam_fields = next(lines).split()
            if len(beam_fields) < 10:
                raise ValueError(f"Malformed init beam line in {path}")
            nprup = int(beam_fields[-1])
            for _ in range(nprup):
                process_fields = next(lines).split()
                if len(process_fields) < 4:
                    raise ValueError(f"Malformed init process line in {path}")
                init_process_ids.add(int(process_fields[3]))
            break

    if not init_process_ids:
        raise ValueError(f"No declared init process IDs found in {path}")

    with path.open() as handle:
        lines = iter(handle)
        for line in lines:
            if line.strip() != "<event>":
                continue
            header = next(lines).split()
            if len(header) < 2:
                raise ValueError(f"Malformed event header in {path}")
            idprup = int(header[1])
            if idprup not in init_process_ids:
                raise ValueError(
                    f"Event IDPRUP={idprup} is not declared by init LPRUP values "
                    f"{sorted(init_process_ids)} in {path}"
                )


def count_sidecar_rows(path: Path) -> int:
    count = 0
    with path.open() as handle:
        for line in handle:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                count += 1
    return count


def lhe_has_closing_tag(path: Path) -> bool:
    last_nonempty = ""
    with path.open(errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                last_nonempty = stripped
    return last_nonempty == "</LesHouchesEvents>"


def validate_forced_output_pair(forced_lhe: Path, sidecar: Path) -> tuple[int, int]:
    if not forced_lhe.exists():
        raise RunError(f"forced Herwig LHE was not written: {forced_lhe.name}")
    if not sidecar.exists():
        raise RunError(f"force sidecar was not written: {sidecar.name}")
    if not lhe_has_closing_tag(forced_lhe):
        raise RunError(f"forced Herwig LHE is not closed: {forced_lhe.name}")

    forced_events = count_lhe_events(forced_lhe)
    sidecar_rows = count_sidecar_rows(sidecar)
    if forced_events <= 0:
        raise RunError(f"forced Herwig LHE contains no events: {forced_lhe.name}")
    if sidecar_rows != forced_events:
        raise RunError(
            f"sidecar rows ({sidecar_rows}) do not match forced events ({forced_events})"
        )
    return forced_events, sidecar_rows


def parse_unw_par(path: Path) -> dict[str, float | int | None]:
    xsec = None
    xerr = None
    unw_events = None
    lum = None
    for line in path.read_text().splitlines():
        if "Crosssection +- error" in line:
            fields = line.split("!", 1)[0].split()
            xsec = float(fields[0])
            xerr = float(fields[1])
        elif "unwtd events" in line:
            fields = line.split("!", 1)[0].split()
            unw_events = int(fields[0])
            lum = float(fields[1])
    return {
        "xsec_pb": xsec,
        "xerr_pb": xerr,
        "unweighted_events": unw_events,
        "luminosity_pb_inv": lum,
    }


def parse_init_xsec(path: Path) -> dict[str, float]:
    _, process = extract_lhe_init(path)
    return {
        "xsec_pb": float(process[0]),
        "xerr_pb": float(process[1]),
    }


def parse_oversampling(path: Path) -> float | None:
    if not path.exists():
        return None
    pattern = re.compile(r"oversampled.*factor\s+([0-9.eE+-]+)")
    for line in path.read_text(errors="replace").splitlines():
        match = pattern.search(line)
        if match:
            return float(match.group(1))
    return None


def prune_herwig_intermediates(run_dir: Path, herwig_base: str) -> list[dict[str, Any]]:
    """Remove regenerateable Herwig artifacts after final validation."""
    removed: list[dict[str, Any]] = []
    for suffix in (".run", ".dump"):
        path = run_dir / f"{herwig_base}{suffix}"
        if not path.exists():
            continue
        size = path.stat().st_size
        path.unlink()
        removed.append({"path": rel(path), "bytes": size})
    return removed


def choose_herwig_events(input_events: int, herwig_events: str, fraction: float) -> int:
    if input_events <= 0:
        raise ValueError("converted LHE contains no events")
    if herwig_events == "all":
        return input_events
    if herwig_events == "fraction":
        return max(1, int(math.floor(input_events * fraction)))
    try:
        requested = int(herwig_events)
    except ValueError as exc:
        raise ValueError("--herwig-events must be 'all', 'fraction', or an integer") from exc
    return max(1, requested)


def reweight_and_validate_forced_output(
    args: argparse.Namespace,
    manifest: dict[str, Any],
    progress_queue: queue.Queue[dict[str, Any]] | None,
    run_index: int,
    tag: str,
    run_dir: Path,
    unw_par: Path,
    converted_lhe: Path,
    forced_lhe: Path,
    sidecar: Path,
    reweighted_lhe: Path,
    alpgen_stats: dict[str, float | int | None],
    herwig_base: str,
    partial: bool = False,
) -> dict[str, Any]:
    forced_events, sidecar_rows = validate_forced_output_pair(forced_lhe, sidecar)
    xerr = alpgen_stats["xerr_pb"]
    if xerr is None or not math.isfinite(float(xerr)):
        raise RunError(f"could not parse finite AlpGen cross-section error from {unw_par}")

    message = ""
    if partial:
        message = f"salvage {forced_events} partial events after Herwig error"
    set_stage(manifest, progress_queue, run_index, tag, "reweight", message)
    manifest["commands"].append(
        run_command(
            [
                sys.executable,
                str(args.reweight_script),
                "--input-xsec-error",
                str(xerr),
                forced_lhe.name,
                sidecar.name,
                reweighted_lhe.name,
            ],
            run_dir,
            run_dir / f"{tag}_reweight.stdout",
            run_dir / f"{tag}_reweight.stderr",
        )
    )

    set_stage(manifest, progress_queue, run_index, tag, "validate")
    validate_lhe_declared_processes(reweighted_lhe)
    final_summary = parse_lhe_event_summary(reweighted_lhe)
    init_xsec = parse_init_xsec(reweighted_lhe)
    if final_summary["events"] != forced_events:
        raise RunError(
            f"final events ({final_summary['events']}) do not match forced events ({forced_events})"
        )
    if final_summary["bad_final_state_events"]:
        raise RunError(
            f"{final_summary['bad_final_state_events']} events are not final 8b states"
        )

    manifest["events"].update(
        {
            "forced_lhe": forced_events,
            "sidecar_rows": sidecar_rows,
            "final_reweighted": final_summary["events"],
            "final_bad_state": final_summary["bad_final_state_events"],
            "final_sum_weights": final_summary["sum_weights"],
        }
    )
    manifest["corrected_xsec"] = init_xsec
    manifest["files"].update(
        {
            "weighted_events": rel(run_dir / f"{tag}.wgt"),
            "unweighted_events": rel(run_dir / f"{tag}.unw"),
            "unweighted_parameters": rel(unw_par),
            "converted_lhe": rel(converted_lhe),
            "forced_lhe": rel(forced_lhe),
            "force_sidecar": rel(sidecar),
            "reweighted_lhe": rel(reweighted_lhe),
        }
    )
    manifest["herwig_oversampling_factor"] = parse_oversampling(
        run_dir / f"{herwig_base}.out"
    )
    return {
        "forced_events": forced_events,
        "sidecar_rows": sidecar_rows,
        "final_summary": final_summary,
        "init_xsec": init_xsec,
    }


def plan_run(args: argparse.Namespace, run_index: int) -> dict[str, Any]:
    tag = f"{args.tag_prefix}_r{run_index:06d}"
    run_dir = args.campaign_dir / f"run_{run_index:06d}"
    return {
        "run_index": run_index,
        "tag": tag,
        "run_dir": rel(run_dir),
        "mode1_input": rel(run_dir / f"{tag}_mode1.in"),
        "mode2_input": rel(run_dir / f"{tag}_mode2.in"),
        "herwig_input": rel(run_dir / f"{tag}_Herwig.in"),
        "final_lhe": rel(run_dir / f"{tag}_Herwig-Reweighted.lhe"),
    }


def run_one(
    args: argparse.Namespace,
    run_index: int,
    progress_queue: queue.Queue[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tag = f"{args.tag_prefix}_r{run_index:06d}"
    run_dir = args.campaign_dir / f"run_{run_index:06d}"
    if run_dir.exists():
        raise RunError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)

    manifest: dict[str, Any] = {
        "campaign": args.campaign,
        "run_index": run_index,
        "tag": tag,
        "run_dir": rel(run_dir),
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "commands": [],
        "files": {},
    }
    manifest_path = run_dir / "run_manifest.json"

    try:
        set_stage(manifest, progress_queue, run_index, tag, "setup", "copy inputs")
        template_copy = run_dir / f"{tag}_source_{args.template.name}"
        herwig_template_copy = run_dir / f"{tag}_source_{args.herwig_template.name}"
        shutil.copy2(args.template, template_copy)
        shutil.copy2(args.herwig_template, herwig_template_copy)

        manifest["files"]["template_copy"] = rel(template_copy)
        manifest["files"]["herwig_template_copy"] = rel(herwig_template_copy)
        manifest["input_template_sha256"] = sha256_file(args.template)
        manifest["herwig_template_sha256"] = sha256_file(args.herwig_template)

        seeds = {
            "iseed1": seed(args.base_seed, run_index, 7919),
            "iseed2": seed(args.base_seed, run_index, 104729),
            "iseed3": seed(args.base_seed, run_index, 15485863),
            "iseed4": seed(args.base_seed, run_index, 32452843),
            "herwig": args.herwig_seed_base + run_index,
        }
        manifest["seeds"] = seeds

        mode1_input = run_dir / f"{tag}_mode1.in"
        mode2_input = run_dir / f"{tag}_mode2.in"
        write_mode1_input(args.template, mode1_input, tag, (seeds["iseed1"], seeds["iseed2"]))
        write_mode2_input(mode2_input, tag, (seeds["iseed3"], seeds["iseed4"]))
        manifest["files"]["mode1_input"] = rel(mode1_input)
        manifest["files"]["mode2_input"] = rel(mode2_input)
        manifest["alpgen_mode1_workload"] = args.mode1_workload

        set_stage(
            manifest,
            progress_queue,
            run_index,
            tag,
            "alpgen_mode1",
            f"{format_count(args.mode1_workload['total_events'])} requested including warmup",
        )
        manifest["commands"].append(
            run_command_with_input(
                [str(args.alpgen)],
                mode1_input,
                run_dir,
                run_dir / f"{tag}_alpgen_mode1.stdout",
                run_dir / f"{tag}_alpgen_mode1.stderr",
                args.setup_command,
            )
        )
        set_stage(manifest, progress_queue, run_index, tag, "alpgen_mode2")
        manifest["commands"].append(
            run_command_with_input(
                [str(args.alpgen)],
                mode2_input,
                run_dir,
                run_dir / f"{tag}_alpgen_mode2.stdout",
                run_dir / f"{tag}_alpgen_mode2.stderr",
                args.setup_command,
            )
        )

        unw_par = run_dir / f"{tag}_unw.par"
        alpgen_stats = parse_unw_par(unw_par)
        manifest["alpgen"] = alpgen_stats

        set_stage(manifest, progress_queue, run_index, tag, "alpgentolh")
        manifest["commands"].append(
            run_command(
                [str(args.alpgentolh), tag],
                run_dir,
                run_dir / f"{tag}_alpgentolh.stdout",
                run_dir / f"{tag}_alpgentolh.stderr",
            )
        )

        converted_lhe = run_dir / f"{tag}.lhe"
        input_events = count_lhe_events(converted_lhe)
        requested_herwig_events = choose_herwig_events(
            input_events,
            args.herwig_events,
            args.herwig_event_fraction,
        )
        manifest["events"] = {
            "converted_lhe": input_events,
            "requested_herwig": requested_herwig_events,
        }

        set_stage(
            manifest,
            progress_queue,
            run_index,
            tag,
            "herwig_prepare",
            f"{input_events} input events, requesting {requested_herwig_events}",
        )
        herwig_base = f"{tag}_Herwig"
        herwig_input = run_dir / f"{herwig_base}.in"
        correction_file = f"{herwig_base}.force8b.weights"
        write_herwig_input(
            args.herwig_template,
            herwig_input,
            converted_lhe.name,
            herwig_base,
            correction_file,
            requested_herwig_events,
            seeds["herwig"],
        )
        manifest["files"]["herwig_input"] = rel(herwig_input)

        set_stage(manifest, progress_queue, run_index, tag, "herwig_read")
        manifest["commands"].append(
            run_command(
                [args.herwig_command, "read", herwig_input.name],
                run_dir,
                run_dir / f"{tag}_herwig_read.stdout",
                run_dir / f"{tag}_herwig_read.stderr",
                args.setup_command,
            )
        )
        set_stage(manifest, progress_queue, run_index, tag, "herwig_run")
        herwig_run_result = run_command(
            [args.herwig_command, "run", f"{herwig_base}.run"],
            run_dir,
            run_dir / f"{tag}_herwig_run.stdout",
            run_dir / f"{tag}_herwig_run.stderr",
            args.setup_command,
            check=False,
        )
        manifest["commands"].append(herwig_run_result)

        forced_lhe = run_dir / f"{herwig_base}.lhe"
        sidecar = run_dir / correction_file
        reweighted_lhe = run_dir / f"{herwig_base}-Reweighted.lhe"
        partial = False
        if herwig_run_result["returncode"] != 0:
            herwig_error = command_failure_message(herwig_run_result)
            manifest["herwig_run_error"] = herwig_error
            manifest.setdefault("stage_history", []).append(
                {
                    "stage": "herwig_run_error",
                    "timestamp": datetime.now().isoformat(),
                    "error": herwig_error,
                }
            )
            if not args.salvage_failed_herwig:
                raise RunError(herwig_error)
            partial = True

        finalization = reweight_and_validate_forced_output(
            args,
            manifest,
            progress_queue,
            run_index,
            tag,
            run_dir,
            unw_par,
            converted_lhe,
            forced_lhe,
            sidecar,
            reweighted_lhe,
            alpgen_stats,
            herwig_base,
            partial=partial,
        )
        manifest["status"] = "success_partial" if partial else "success"
        if partial:
            manifest["salvaged_partial_herwig"] = True
        if args.prune_herwig_intermediates:
            removed = prune_herwig_intermediates(run_dir, herwig_base)
            if removed:
                manifest.setdefault("pruned_files", []).extend(removed)
        manifest["current_stage"] = "complete"
        manifest.setdefault("stage_history", []).append(
            {"stage": "complete", "timestamp": datetime.now().isoformat()}
        )
        emit_progress(
            progress_queue,
            run_index,
            tag,
            "complete",
            status=manifest["status"],
            events=int(finalization["final_summary"]["events"]),
        )
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        manifest["current_stage"] = "failed"
        manifest.setdefault("stage_history", []).append(
            {
                "stage": "failed",
                "timestamp": datetime.now().isoformat(),
                "error": str(exc),
            }
        )
        emit_progress(
            progress_queue,
            run_index,
            tag,
            "failed",
            status="failed",
            error=str(exc),
        )
        atomic_write_json(manifest_path, manifest)
        raise
    finally:
        manifest["finished_at"] = datetime.now().isoformat()
        atomic_write_json(manifest_path, manifest)

    return manifest


def merge_lhe(campaign_dir: Path, campaign: str, run_manifests: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [item for item in run_manifests if item.get("status") in SUCCESS_STATUSES]
    if not successful:
        raise RunError("no successful runs to merge")

    merged_dir = campaign_dir / "merged"
    merged_dir.mkdir(exist_ok=True)
    merged_lhe = merged_dir / f"{campaign}_8b_reweighted_merged.lhe"

    event_counts = [int(item["events"]["final_reweighted"]) for item in successful]
    total_events = sum(event_counts)
    if total_events <= 0:
        raise RunError("successful runs contain no final events")

    xsecs = [float(item["corrected_xsec"]["xsec_pb"]) for item in successful]
    xerrs = [float(item["corrected_xsec"]["xerr_pb"]) for item in successful]
    merged_xsec = sum(n * x for n, x in zip(event_counts, xsecs)) / total_events
    merged_xerr = math.sqrt(sum((n * e) ** 2 for n, e in zip(event_counts, xerrs))) / total_events
    total_sum_weights = sum(float(item["events"]["final_sum_weights"]) for item in successful)

    first_lhe = Path(successful[0]["files"]["reweighted_lhe"])
    if not first_lhe.is_absolute():
        first_lhe = REPO_ROOT / first_lhe
    init_beam, init_process = extract_lhe_init(first_lhe)
    init_process = init_process.copy()
    init_process[0] = f"{merged_xsec:.9e}"
    init_process[1] = f"{merged_xerr:.9e}"

    with merged_lhe.open("w") as out:
        out.write('<LesHouchesEvents version="3.0">\n')
        out.write("<header>\n")
        out.write(f"<!-- Campaign: {campaign} -->\n")
        out.write(f"<!-- Source runs: {len(successful)} -->\n")
        out.write(
            f"<!-- Partial Herwig salvages: "
            f"{sum(1 for item in successful if item.get('status') == 'success_partial')} -->\n"
        )
        out.write(f"<!-- Total events: {total_events} -->\n")
        out.write(f"<!-- Total sum of event weights: {total_sum_weights:.16e} -->\n")
        out.write(
            f"<!-- Merged XSECUP: {merged_xsec:.9e} pb; XERRUP: {merged_xerr:.9e} pb. -->\n"
        )
        for item in successful:
            out.write(
                "<!-- {tag}: events={events} xsec={xsec:.9e} pb xerr={xerr:.9e} pb -->\n".format(
                    tag=item["tag"],
                    events=item["events"]["final_reweighted"],
                    xsec=float(item["corrected_xsec"]["xsec_pb"]),
                    xerr=float(item["corrected_xsec"]["xerr_pb"]),
                )
            )
        out.write("</header>\n")
        out.write("<init>\n")
        out.write("  " + "  ".join(init_beam) + "\n")
        out.write("  " + "  ".join(init_process) + "\n")
        out.write("</init>\n")
        for item in successful:
            lhe_path = Path(item["files"]["reweighted_lhe"])
            if not lhe_path.is_absolute():
                lhe_path = REPO_ROOT / lhe_path
            for event in iter_lhe_events(lhe_path):
                out.write(event)
        out.write("</LesHouchesEvents>\n")

    return {
        "merged_lhe": rel(merged_lhe),
        "source_runs": len(successful),
        "events": total_events,
        "sum_weights": total_sum_weights,
        "xsec_pb": merged_xsec,
        "xerr_pb": merged_xerr,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run parallel 6Qg AlpGen -> Herwig forced 8b campaigns."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--runs", type=int, help="Run exactly this many chains.")
    group.add_argument(
        "--target-events",
        type=int,
        help="Keep launching batches until this many final 8b events are produced.",
    )
    parser.add_argument("--campaign", default=f"6qg8b_{now_stamp()}")
    parser.add_argument("--tag-prefix", default=None)
    parser.add_argument("--jobs", type=int, default=32)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--herwig-template", type=Path, default=DEFAULT_HERWIG_TEMPLATE)
    parser.add_argument("--alpgen", type=Path, default=DEFAULT_ALPGEN)
    parser.add_argument("--alpgentolh", type=Path, default=DEFAULT_ALPGENTOLH)
    parser.add_argument("--reweight-script", type=Path, default=DEFAULT_REWEIGHT)
    parser.add_argument("--herwig-command", default="Herwig")
    parser.add_argument(
        "--setup-command",
        default="",
        help="Optional shell prefix, e.g. 'module load herwig/stable-full-py3-rivet4'.",
    )
    parser.add_argument("--base-seed", type=int, default=12345)
    parser.add_argument("--herwig-seed-base", type=int, default=31122002)
    parser.add_argument(
        "--events-per-run-estimate",
        type=int,
        default=1000,
        help="Initial final-event estimate used with --target-events.",
    )
    parser.add_argument(
        "--herwig-events",
        default="all",
        help="'all', 'fraction', or an integer NumberOfEvents for each Herwig run.",
    )
    parser.add_argument("--herwig-event-fraction", type=float, default=0.65)
    parser.add_argument(
        "--salvage-failed-herwig",
        dest="salvage_failed_herwig",
        action="store_true",
        default=True,
        help=(
            "When Herwig run exits nonzero, keep a closed partial LHE if it has "
            "matching MinBShowerVeto sidecar rows."
        ),
    )
    parser.add_argument(
        "--no-salvage-failed-herwig",
        dest="salvage_failed_herwig",
        action="store_false",
        help="Treat any nonzero Herwig run exit as a failed run.",
    )
    parser.add_argument("--merge", dest="merge", action="store_true", default=True)
    parser.add_argument("--no-merge", dest="merge", action="store_false")
    parser.add_argument(
        "--prune-herwig-intermediates",
        dest="prune_herwig_intermediates",
        action="store_true",
        default=True,
        help="Delete regenerateable Herwig .run/.dump files after final LHE validation.",
    )
    parser.add_argument(
        "--keep-herwig-intermediates",
        dest="prune_herwig_intermediates",
        action="store_false",
        help="Keep Herwig .run/.dump files in each run directory.",
    )
    parser.add_argument("--progress", dest="progress", action="store_true", default=True)
    parser.add_argument("--no-progress", dest="progress", action="store_false")
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=15.0,
        help="Seconds between live progress summaries.",
    )
    parser.add_argument(
        "--alpgen-progress-interval",
        type=float,
        default=5.0,
        help="Seconds between AlpGen .mon/.stat progress polls.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def validate_args(args: argparse.Namespace) -> argparse.Namespace:
    args.template = args.template.resolve()
    args.herwig_template = args.herwig_template.resolve()
    args.alpgen = args.alpgen.resolve()
    args.alpgentolh = args.alpgentolh.resolve()
    args.reweight_script = args.reweight_script.resolve()
    args.campaign = sanitize_tag(args.campaign)
    args.tag_prefix = sanitize_tag(args.tag_prefix or args.campaign)
    args.campaign_dir = CAMPAIGNS_DIR / args.campaign
    args.mode1_workload = parse_mode1_workload(args.template)

    if args.jobs < 1:
        raise ValueError("--jobs must be at least 1")
    if args.start_index < 1:
        raise ValueError("--start-index must be at least 1")
    if args.runs is not None and args.runs < 1:
        raise ValueError("--runs must be at least 1")
    if args.target_events is not None and args.target_events < 1:
        raise ValueError("--target-events must be at least 1")
    if args.events_per_run_estimate < 1:
        raise ValueError("--events-per-run-estimate must be at least 1")
    if args.herwig_event_fraction <= 0 or args.herwig_event_fraction > 1:
        raise ValueError("--herwig-event-fraction must be in (0, 1]")
    if args.progress_interval <= 0:
        raise ValueError("--progress-interval must be positive")
    if args.alpgen_progress_interval <= 0:
        raise ValueError("--alpgen-progress-interval must be positive")

    for path in [args.template, args.herwig_template, args.alpgen, args.alpgentolh, args.reweight_script]:
        if not path.exists():
            raise FileNotFoundError(path)
    return args


def run_batch(args: argparse.Namespace, run_indices: list[int]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    monitor = (
        ProgressMonitor(
            run_indices,
            args.tag_prefix,
            args.progress_interval,
            args.campaign_dir,
            args.mode1_workload,
            args.alpgen_progress_interval,
        )
        if args.progress
        else None
    )
    progress_queue = monitor.queue if monitor else None
    if monitor:
        monitor.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            future_to_index = {
                pool.submit(run_one, args, run_index, progress_queue): run_index
                for run_index in run_indices
            }
            for future in concurrent.futures.as_completed(future_to_index):
                run_index = future_to_index[future]
                try:
                    result = future.result()
                except Exception as exc:
                    run_dir = args.campaign_dir / f"run_{run_index:06d}"
                    tag = f"{args.tag_prefix}_r{run_index:06d}"
                    result = {
                        "campaign": args.campaign,
                        "run_index": run_index,
                        "tag": tag,
                        "run_dir": rel(run_dir),
                        "status": "failed",
                        "error": str(exc),
                    }
                    if not (run_dir / "run_manifest.json").exists():
                        emit_progress(
                            progress_queue,
                            run_index,
                            tag,
                            "failed",
                            status="failed",
                            error=str(exc),
                        )
                results.append(result)
                if not args.progress:
                    print(
                        f"[{result['tag']}] {result['status']}"
                        + (
                            f" events={result.get('events', {}).get('final_reweighted')}"
                            if result.get("status") in SUCCESS_STATUSES
                            else f" error={result.get('error')}"
                        ),
                        flush=True,
                    )
    finally:
        if monitor:
            monitor.stop()
    return sorted(results, key=lambda item: item["run_index"])


def main() -> int:
    parser = build_arg_parser()
    args = validate_args(parser.parse_args())

    if args.dry_run:
        if args.runs is not None:
            runs = args.runs
        else:
            runs = math.ceil(args.target_events / args.events_per_run_estimate)
        planned = [plan_run(args, i) for i in range(args.start_index, args.start_index + runs)]
        print(json.dumps({"campaign_dir": rel(args.campaign_dir), "planned_runs": planned}, indent=2))
        return 0

    if args.campaign_dir.exists():
        raise RunError(f"campaign directory already exists: {args.campaign_dir}")
    args.campaign_dir.mkdir(parents=True)

    campaign_manifest: dict[str, Any] = {
        "campaign": args.campaign,
        "tag_prefix": args.tag_prefix,
        "campaign_dir": rel(args.campaign_dir),
        "started_at": datetime.now().isoformat(),
        "jobs": args.jobs,
        "target_events": args.target_events,
        "requested_runs": args.runs,
        "runs": [],
    }
    manifest_path = args.campaign_dir / "campaign_manifest.json"
    atomic_write_json(manifest_path, campaign_manifest)

    next_index = args.start_index
    total_events = 0
    observed_estimate = args.events_per_run_estimate
    failures = 0

    while True:
        if args.runs is not None:
            remaining_runs = args.start_index + args.runs - next_index
            if remaining_runs <= 0:
                break
            batch_size = remaining_runs
        else:
            remaining_events = args.target_events - total_events
            if remaining_events <= 0:
                break
            batch_size = max(1, math.ceil(remaining_events / observed_estimate))

        run_indices = list(range(next_index, next_index + batch_size))
        next_index += batch_size
        batch_results = run_batch(args, run_indices)
        campaign_manifest["runs"].extend(batch_results)
        successes = [item for item in batch_results if item.get("status") in SUCCESS_STATUSES]
        failures += sum(1 for item in batch_results if item.get("status") not in SUCCESS_STATUSES)
        total_events += sum(int(item["events"]["final_reweighted"]) for item in successes)
        if successes:
            observed_estimate = max(
                1,
                int(
                    sum(int(item["events"]["final_reweighted"]) for item in successes)
                    / len(successes)
                ),
            )
        campaign_manifest["completed_events"] = total_events
        campaign_manifest["observed_events_per_run"] = observed_estimate
        campaign_manifest["partial_success_runs"] = sum(
            1 for item in campaign_manifest["runs"] if item.get("status") == "success_partial"
        )
        atomic_write_json(manifest_path, campaign_manifest)

        if failures and args.runs is not None:
            break
        if failures and not successes:
            break
        if failures and args.target_events is not None and total_events >= args.target_events:
            break

    if args.merge:
        merge_summary = merge_lhe(args.campaign_dir, args.campaign, campaign_manifest["runs"])
        campaign_manifest["merge"] = merge_summary

    campaign_manifest["finished_at"] = datetime.now().isoformat()
    campaign_manifest["failed_runs"] = failures
    campaign_manifest["partial_success_runs"] = sum(
        1 for item in campaign_manifest["runs"] if item.get("status") == "success_partial"
    )
    target_met = args.target_events is None or total_events >= args.target_events
    partial_successes = int(campaign_manifest["partial_success_runs"])
    if args.runs is not None:
        campaign_manifest["status"] = (
            "failed" if failures
            else "success_with_partial" if partial_successes
            else "success"
        )
    else:
        campaign_manifest["status"] = (
            "success_with_failures" if failures and target_met
            else "success_with_partial" if partial_successes and target_met
            else "success" if target_met
            else "failed"
        )
    atomic_write_json(manifest_path, campaign_manifest)
    print(f"Campaign manifest: {manifest_path}")
    if campaign_manifest["status"] == "failed":
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
