#!/usr/bin/env python3
"""Unweight AlpGen 4Q runs, convert to LHE, and merge the LHE files."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_INPUT_PREFIX = "input_4b2j_13.6_LHAPDF_NNPDF23_nlo_as_0119_"
DEFAULT_OUTPUT = "4b2j_13.6_LHAPDF_NNPDF23_nlo_as_0119_merged.lhe"
DEFAULT_SETUP = "module load herwig/stable-full-py3-rivet4"


class RunError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlpgenRun:
    index: int
    input_path: Path
    tag: str
    iseed3: int
    iseed4: int

    @property
    def wgt_path(self) -> Path:
        return Path(f"{self.tag}.wgt")

    @property
    def stat_path(self) -> Path:
        return Path(f"{self.tag}.stat")

    @property
    def unw_path(self) -> Path:
        return Path(f"{self.tag}.unw")

    @property
    def unw_par_path(self) -> Path:
        return Path(f"{self.tag}_unw.par")

    @property
    def lhe_path(self) -> Path:
        return Path(f"{self.tag}.lhe")


def parse_seed(input_path: Path, seed_name: str) -> int:
    for line in input_path.read_text().splitlines():
        data = line.split("!", 1)[0].strip()
        if not data:
            continue
        parts = data.split()
        if len(parts) >= 2 and parts[0].lower() == seed_name.lower():
            return int(float(parts[1]))
    raise RunError(f"{seed_name} is missing in {input_path}")


def discover_runs(cwd: Path, input_prefix: str, only: set[int] | None) -> list[AlpgenRun]:
    escaped = re.escape(input_prefix)
    pattern = re.compile(rf"^{escaped}(?P<idx>\d+)$")
    runs: list[AlpgenRun] = []
    for path in cwd.iterdir():
        match = pattern.match(path.name)
        if not match or not path.is_file():
            continue
        index = int(match.group("idx"))
        if only is not None and index not in only:
            continue
        tag = path.name.removeprefix("input_")
        runs.append(
            AlpgenRun(
                index=index,
                input_path=path,
                tag=tag,
                iseed3=parse_seed(path, "iseed3"),
                iseed4=parse_seed(path, "iseed4"),
            )
        )
    runs.sort(key=lambda item: item.index)
    return runs


def parse_only(value: str | None) -> set[int] | None:
    if not value:
        return None
    selected: set[int] = set()
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start, end = item.split("-", 1)
            selected.update(range(int(start), int(end) + 1))
        else:
            selected.add(int(item))
    return selected


def check_inputs(run: AlpgenRun) -> None:
    missing = [
        str(path)
        for path in (run.input_path, run.wgt_path, run.stat_path, Path(f"{run.tag}.par"))
        if not path.exists()
    ]
    if missing:
        raise RunError(f"{run.tag}: missing required files: {', '.join(missing)}")


def parse_weighted_par_summary(run: AlpgenRun) -> tuple[float, float]:
    par_path = Path(f"{run.tag}.par")
    lines = par_path.read_text(errors="replace").splitlines()
    for index, line in enumerate(lines):
        if "number wgted evts in the file" not in line:
            continue
        if index + 1 >= len(lines):
            break
        fields = lines[index + 1].replace("D", "E").split()
        if len(fields) < 3:
            break
        return float(fields[1]), float(fields[2])
    raise RunError(f"{run.tag}: could not parse weighted sigma/error from {par_path}")


def filter_invalid_weighted_runs(
    runs: list[AlpgenRun], skip_invalid: bool
) -> tuple[list[AlpgenRun], list[dict[str, object]]]:
    valid: list[AlpgenRun] = []
    invalid: list[dict[str, object]] = []
    for run in runs:
        xsec, xerr = parse_weighted_par_summary(run)
        if math.isfinite(xsec) and math.isfinite(xerr) and xerr > 0.0:
            valid.append(run)
        else:
            invalid.append(
                {
                    "index": run.index,
                    "tag": run.tag,
                    "weighted_xsec_pb": xsec,
                    "weighted_xerr_pb": xerr,
                }
            )

    if invalid and not skip_invalid:
        bad = ", ".join(f"{item['index']}:{item['tag']}" for item in invalid)
        raise RunError(
            "invalid weighted runs found; rerun with --skip-invalid-weighted to exclude: "
            + bad
        )
    return valid, invalid


def write_mode2_input(run: AlpgenRun, path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "2         ! read weighted events for unweighting",
                f"{run.tag} ! string labeling input/output files",
                f"iseed3 {run.iseed3}",
                f"iseed4 {run.iseed4}",
                "eoi 1 ! end of input",
                "",
            ]
        )
    )


def run_command(
    argv: list[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    setup_command: str,
    stdin_text: str | None = None,
) -> dict[str, object]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()

    if setup_command:
        command = ["bash", "-lc", setup_command + '\nexec "$@"', "bash"] + argv
    else:
        command = argv

    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        proc = subprocess.run(
            command,
            input=stdin_text,
            cwd=cwd,
            stdout=stdout,
            stderr=stderr,
            text=True,
            check=False,
        )

    result = {
        "argv": argv,
        "returncode": proc.returncode,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "elapsed_seconds": time.time() - start,
    }
    if proc.returncode != 0:
        raise RunError(
            f"command failed for {' '.join(argv)}; see {stdout_path} and {stderr_path}"
        )
    return result


def unweight_run(args: argparse.Namespace, run: AlpgenRun) -> dict[str, object]:
    if (
        not args.force_unweight
        and run.unw_path.exists()
        and run.unw_par_path.exists()
        and run.unw_path.stat().st_size > 0
        and run.unw_par_path.stat().st_size > 0
    ):
        return {"stage": "unweight", "status": "skipped_existing"}

    mode2_path = args.log_dir / f"{run.tag}_mode2.in"
    write_mode2_input(run, mode2_path)
    return run_command(
        [str(args.alpgen)],
        args.cwd,
        args.log_dir / f"{run.tag}_4qgen_mode2.stdout",
        args.log_dir / f"{run.tag}_4qgen_mode2.stderr",
        args.setup_command,
        stdin_text=mode2_path.read_text(),
    )


def convert_run(args: argparse.Namespace, run: AlpgenRun) -> dict[str, object]:
    if not args.force_convert and run.lhe_path.exists() and run.lhe_path.stat().st_size > 0:
        try:
            expected_events = int(parse_unw_par(run.unw_par_path)["unweighted_events"])
            actual_events = count_lhe_events(run.lhe_path)
        except (OSError, RunError, ValueError):
            expected_events = -1
            actual_events = -2
        if expected_events == actual_events and actual_events > 0:
            return {"stage": "convert", "status": "skipped_existing"}

    if not run.unw_path.exists() or not run.unw_par_path.exists():
        raise RunError(f"{run.tag}: missing unweighted files before conversion")

    return run_command(
        [str(args.alpgentolh), run.tag],
        args.cwd,
        args.log_dir / f"{run.tag}_alpgentolh.stdout",
        args.log_dir / f"{run.tag}_alpgentolh.stderr",
        args.setup_command,
    )


def parse_unw_par(path: Path) -> dict[str, float | int]:
    xsec = None
    xerr = None
    events = None
    lum = None
    for line in path.read_text(errors="replace").splitlines():
        if "Crosssection +- error" in line:
            fields = line.split("!", 1)[0].split()
            xsec = float(fields[0])
            xerr = float(fields[1])
        elif "unwtd events" in line:
            fields = line.split("!", 1)[0].split()
            events = int(fields[0])
            lum = float(fields[1])
    if xsec is None or xerr is None or events is None or lum is None:
        raise RunError(f"could not parse cross-section summary from {path}")
    return {
        "xsec_pb": xsec,
        "xerr_pb": xerr,
        "unweighted_events": events,
        "luminosity_pb_inv": lum,
    }


def count_lhe_events(path: Path) -> int:
    count = 0
    with path.open(errors="replace") as handle:
        for line in handle:
            if line.strip() == "<event>":
                count += 1
    return count


def lhe_has_closing_tag(path: Path) -> bool:
    last = ""
    with path.open(errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                last = stripped
    return last == "</LesHouchesEvents>"


def extract_lhe_init(path: Path) -> tuple[list[str], list[str]]:
    with path.open(errors="replace") as handle:
        iterator = iter(handle)
        for line in iterator:
            if line.strip() == "<init>":
                return next(iterator).split(), next(iterator).split()
    raise RunError(f"no <init> block found in {path}")


def iter_lhe_events(path: Path) -> Iterable[str]:
    in_event = False
    buffer: list[str] = []
    with path.open(errors="replace") as handle:
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


def parse_lhe_first_event_process(path: Path) -> int | None:
    with path.open(errors="replace") as handle:
        lines = iter(handle)
        for line in lines:
            if line.strip() != "<event>":
                continue
            header = next(lines).split()
            if len(header) >= 2:
                return int(header[1])
    return None


def inverse_variance_xsec(rows: list[dict[str, float | int | str]]) -> tuple[float, float]:
    weighted_sum = 0.0
    weight_sum = 0.0
    for row in rows:
        xsec = float(row["xsec_pb"])
        xerr = float(row["xerr_pb"])
        if not math.isfinite(xsec) or not math.isfinite(xerr) or xerr <= 0.0:
            raise RunError(f"invalid cross section/error for {row['tag']}: {xsec} +/- {xerr}")
        weight = 1.0 / (xerr * xerr)
        weighted_sum += weight * xsec
        weight_sum += weight
    return weighted_sum / weight_sum, 1.0 / math.sqrt(weight_sum)


def event_weighted_xsec(rows: list[dict[str, float | int | str]]) -> tuple[float, float]:
    total_events = sum(int(row["lhe_events"]) for row in rows)
    if total_events <= 0:
        raise RunError("no LHE events available for merge")
    xsec = sum(int(row["lhe_events"]) * float(row["xsec_pb"]) for row in rows) / total_events
    xerr = (
        math.sqrt(
            sum((int(row["lhe_events"]) * float(row["xerr_pb"])) ** 2 for row in rows)
        )
        / total_events
    )
    return xsec, xerr


def build_rows(runs: list[AlpgenRun]) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    for run in runs:
        if not run.lhe_path.exists():
            raise RunError(f"{run.tag}: missing LHE file")
        stats = parse_unw_par(run.unw_par_path)
        lhe_events = count_lhe_events(run.lhe_path)
        if int(stats["unweighted_events"]) != lhe_events:
            raise RunError(
                f"{run.tag}: _unw.par has {stats['unweighted_events']} events, "
                f"but LHE has {lhe_events}"
            )
        rows.append(
            {
                "index": run.index,
                "tag": run.tag,
                "lhe": str(run.lhe_path),
                "xsec_pb": float(stats["xsec_pb"]),
                "xerr_pb": float(stats["xerr_pb"]),
                "unweighted_events": int(stats["unweighted_events"]),
                "lhe_events": lhe_events,
                "luminosity_pb_inv": float(stats["luminosity_pb_inv"]),
            }
        )
    return rows


def merge_lhe(args: argparse.Namespace, runs: list[AlpgenRun]) -> dict[str, object]:
    rows = build_rows(runs)
    combined_xsec, combined_xerr = inverse_variance_xsec(rows)
    event_xsec, event_xerr = event_weighted_xsec(rows)
    total_events = sum(int(row["lhe_events"]) for row in rows)
    total_lumi = sum(float(row["luminosity_pb_inv"]) for row in rows)

    first_lhe = Path(str(rows[0]["lhe"]))
    init_beam, init_process = extract_lhe_init(first_lhe)
    process_id = parse_lhe_first_event_process(first_lhe)
    init_process = init_process.copy()
    init_process[0] = f"{combined_xsec:.9e}"
    init_process[1] = f"{combined_xerr:.9e}"
    if process_id is not None:
        init_process[3] = str(process_id)

    output = Path(args.output)
    tmp_output = output.with_name(output.name + ".tmp")
    with tmp_output.open("w") as out:
        out.write('<LesHouchesEvents version ="1.0">\n')
        out.write("<!--\n")
        out.write("Merged AlpGenToLH sample\n")
        out.write(f"Input prefix: {args.input_prefix}\n")
        out.write(f"Source runs: {len(rows)}\n")
        out.write(f"Total events: {total_events}\n")
        out.write(
            "Combined cross-section estimator: inverse-variance weighted "
            "mean of independent AlpGen run estimates\n"
        )
        out.write(f"Combined XSECUP: {combined_xsec:.12e} pb\n")
        out.write(f"Combined XERRUP: {combined_xerr:.12e} pb\n")
        out.write(f"Event-count weighted cross-check: {event_xsec:.12e} +- {event_xerr:.12e} pb\n")
        out.write(f"Summed run luminosity: {total_lumi:.12e} pb-1\n")
        for row in rows:
            out.write(
                "{tag}: events={events} xsec={xsec:.12e} pb xerr={xerr:.12e} pb "
                "lum={lum:.12e} pb-1\n".format(
                    tag=row["tag"],
                    events=row["lhe_events"],
                    xsec=float(row["xsec_pb"]),
                    xerr=float(row["xerr_pb"]),
                    lum=float(row["luminosity_pb_inv"]),
                )
            )
        out.write("-->\n")
        out.write("<init>\n")
        out.write("  " + "  ".join(init_beam) + "\n")
        out.write("  " + "  ".join(init_process) + "\n")
        out.write("</init>\n")
        for row in rows:
            for event in iter_lhe_events(Path(str(row["lhe"]))):
                out.write(event)
        out.write("</LesHouchesEvents>\n")

    tmp_output.replace(output)
    summary = {
        "merged_lhe": str(output),
        "source_runs": len(rows),
        "events": total_events,
        "combined_xsec_pb": combined_xsec,
        "combined_xerr_pb": combined_xerr,
        "event_weighted_xsec_pb": event_xsec,
        "event_weighted_xerr_pb": event_xerr,
        "summed_luminosity_pb_inv": total_lumi,
        "runs": rows,
    }
    Path(str(output) + ".summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def process_run(
    args: argparse.Namespace, run: AlpgenRun, ordinal: int, total: int
) -> list[dict[str, object]]:
    print(f"[{ordinal}/{total}] unweight {run.tag}", flush=True)
    commands = [unweight_run(args, run)]
    print(f"[{ordinal}/{total}] convert  {run.tag}", flush=True)
    commands.append(convert_run(args, run))
    stats = parse_unw_par(run.unw_par_path)
    print(
        "[{ordinal}/{total}] done     {tag}: events={events} xsec={xsec:.9e} +- {xerr:.9e} pb".format(
            ordinal=ordinal,
            total=total,
            tag=run.tag,
            events=stats["unweighted_events"],
            xsec=stats["xsec_pb"],
            xerr=stats["xerr_pb"],
        ),
        flush=True,
    )
    return commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-prefix", default=DEFAULT_INPUT_PREFIX)
    parser.add_argument("--only", help="comma-separated run indices/ranges, e.g. 0,3,8-12")
    parser.add_argument("--alpgen", type=Path, default=Path("./4Qgen"))
    parser.add_argument("--alpgentolh", type=Path, default=Path("../alpgentolh/AlpGenToLH"))
    parser.add_argument("--setup-command", default=DEFAULT_SETUP)
    parser.add_argument("--log-dir", type=Path, default=Path("alpgen_unweight_lhe_logs"))
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--only-merge", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--jobs", type=int, default=1, help="run this many unweight/convert pipelines in parallel")
    parser.add_argument("--force-unweight", action="store_true")
    parser.add_argument("--force-convert", action="store_true")
    parser.add_argument("--force-merge", action="store_true")
    parser.add_argument(
        "--skip-invalid-weighted",
        action="store_true",
        help="exclude runs whose weighted .par summary has non-finite sigma/error",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.jobs < 1:
        raise RunError("--jobs must be at least 1")
    args.cwd = Path.cwd()
    if not args.alpgen.is_absolute():
        args.alpgen = (args.cwd / args.alpgen).resolve()
    if not args.alpgentolh.is_absolute():
        args.alpgentolh = (args.cwd / args.alpgentolh).resolve()
    args.log_dir.mkdir(parents=True, exist_ok=True)
    runs = discover_runs(args.cwd, args.input_prefix, parse_only(args.only))
    if not runs:
        raise RunError(f"no runs found for prefix {args.input_prefix!r}")

    for run in runs:
        check_inputs(run)
    runs, invalid_runs = filter_invalid_weighted_runs(runs, args.skip_invalid_weighted)
    if not runs:
        raise RunError("no valid runs remain after filtering invalid weighted summaries")

    print(f"Discovered {len(runs)} runs: {runs[0].index}..{runs[-1].index}", flush=True)
    if invalid_runs:
        print(
            "Skipping invalid weighted runs: "
            + ", ".join(str(item["index"]) for item in invalid_runs),
            flush=True,
        )
    if args.dry_run:
        for run in runs:
            print(f"{run.index:03d} {run.tag} seeds=({run.iseed3},{run.iseed4})")
        return 0

    command_log: list[dict[str, object]] = []
    if not args.only_merge:
        jobs = min(args.jobs, len(runs))
        if jobs == 1:
            for ordinal, run in enumerate(runs, start=1):
                command_log.extend(process_run(args, run, ordinal, len(runs)))
        else:
            print(f"Running {jobs} unweight/convert pipelines in parallel", flush=True)
            with ThreadPoolExecutor(max_workers=jobs) as executor:
                futures = {
                    executor.submit(process_run, args, run, ordinal, len(runs)): run
                    for ordinal, run in enumerate(runs, start=1)
                }
                for future in as_completed(futures):
                    run = futures[future]
                    try:
                        command_log.extend(future.result())
                    except Exception as exc:
                        raise RunError(f"{run.tag}: parallel worker failed: {exc}") from exc

    output = Path(args.output)
    if output.exists() and not args.force_merge:
        print(f"Merged LHE exists, replacing because merge inputs may have changed: {output}", flush=True)
    print("Merging LHE files", flush=True)
    summary = merge_lhe(args, runs)
    summary["commands"] = command_log
    summary["skipped_invalid_weighted_runs"] = invalid_runs
    Path(str(output) + ".summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        "Merged {events} events into {path}; XSECUP={xsec:.9e} pb, XERRUP={xerr:.9e} pb".format(
            events=summary["events"],
            path=summary["merged_lhe"],
            xsec=summary["combined_xsec_pb"],
            xerr=summary["combined_xerr_pb"],
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
