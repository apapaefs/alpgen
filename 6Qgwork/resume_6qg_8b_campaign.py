#!/usr/bin/env python3
"""Resume an interrupted 6Qg -> forced 8b campaign."""

from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

import run_6qg_8b_campaign as campaign
import salvage_6qg_herwig_partials as salvage


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def find_campaign_dir(value: str) -> Path:
    path = Path(value)
    if not path.exists():
        path = campaign.CAMPAIGNS_DIR / value
    return path.resolve()


def run_index_from_dir(run_dir: Path) -> int:
    match = re.fullmatch(r"run_(\d+)", run_dir.name)
    if not match:
        raise ValueError(f"not a run directory: {run_dir}")
    return int(match.group(1))


def infer_setup_command(campaign_dir: Path) -> str:
    for manifest_path in sorted(campaign_dir.glob("run_*/run_manifest.json")):
        try:
            manifest = load_json(manifest_path)
        except Exception:
            continue
        for command in manifest.get("commands", []):
            text = command.get("command", "")
            if " && " in text:
                return text.split(" && ", 1)[0]
    return ""


def find_first_source(campaign_dir: Path, pattern: str) -> Path | None:
    matches = sorted(campaign_dir.glob(f"run_*/*{pattern}*"))
    if not matches:
        matches = sorted(campaign_dir.glob(f"*{pattern}*"))
    return matches[0] if matches else None


def parse_seed_input(path: Path) -> dict[str, int]:
    seeds: dict[str, int] = {}
    if not path.exists():
        return seeds
    for line in path.read_text(errors="replace").splitlines():
        fields = campaign.tokens_before_comment(line)
        if len(fields) >= 2 and fields[0].lower().startswith("iseed"):
            seeds[fields[0].lower()] = int(campaign.fortran_float(fields[1]))
    return seeds


def existing_run_stage(run_dir: Path, tag: str) -> str:
    files = {path.name for path in run_dir.iterdir() if path.is_file()}
    if f"{tag}_Herwig-Reweighted.lhe" in files:
        return "reweighted"
    if f"{tag}_Herwig.lhe" in files or f"{tag}_Herwig.force8b.weights" in files:
        return "herwig_output"
    if f"{tag}_Herwig.run" in files:
        return "herwig_read"
    if f"{tag}_Herwig.in" in files:
        return "herwig_prepare"
    if f"{tag}.lhe" in files:
        return "alpgentolh"
    if f"{tag}.unw" in files:
        return "alpgen_mode2"
    if f"{tag}.wgt" in files:
        return "alpgen_mode1"
    return "empty"


def manifest_for_existing_run(args: argparse.Namespace, run_dir: Path, tag: str) -> dict[str, Any]:
    run_index = run_index_from_dir(run_dir)
    mode1_input = run_dir / f"{tag}_mode1.in"
    mode2_input = run_dir / f"{tag}_mode2.in"
    source_template = find_first_source(run_dir, "_source_input_")
    source_herwig = find_first_source(run_dir, "_source_AlpGen8Q-LHEWriter.in")
    mode1_seeds = parse_seed_input(mode1_input)
    mode2_seeds = parse_seed_input(mode2_input)

    manifest: dict[str, Any] = {
        "campaign": args.campaign,
        "run_index": run_index,
        "tag": tag,
        "run_dir": campaign.rel(run_dir),
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "resumed_at": datetime.now().isoformat(),
        "resume_start_stage": existing_run_stage(run_dir, tag),
        "commands": [],
        "files": {
            "mode1_input": campaign.rel(mode1_input),
            "mode2_input": campaign.rel(mode2_input),
        },
        "alpgen_mode1_workload": args.mode1_workload,
        "seeds": {
            "iseed1": mode1_seeds.get("iseed1", campaign.seed(args.base_seed, run_index, 7919)),
            "iseed2": mode1_seeds.get("iseed2", campaign.seed(args.base_seed, run_index, 104729)),
            "iseed3": mode2_seeds.get("iseed3", campaign.seed(args.base_seed, run_index, 15485863)),
            "iseed4": mode2_seeds.get("iseed4", campaign.seed(args.base_seed, run_index, 32452843)),
            "herwig": args.herwig_seed_base + run_index,
        },
    }
    if source_template:
        manifest["files"]["template_copy"] = campaign.rel(source_template)
        manifest["input_template_sha256"] = campaign.sha256_file(source_template)
    if source_herwig:
        manifest["files"]["herwig_template_copy"] = campaign.rel(source_herwig)
        manifest["herwig_template_sha256"] = campaign.sha256_file(source_herwig)
    return manifest


def finish_existing_run(
    args: argparse.Namespace,
    run_dir: Path,
) -> dict[str, Any]:
    run_index = run_index_from_dir(run_dir)
    tag = f"{args.tag_prefix}_r{run_index:06d}"
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.exists():
        return load_json(manifest_path)

    manifest = manifest_for_existing_run(args, run_dir, tag)
    try:
        mode2_input = run_dir / f"{tag}_mode2.in"
        if not mode2_input.exists():
            campaign.write_mode2_input(
                mode2_input,
                tag,
                (manifest["seeds"]["iseed3"], manifest["seeds"]["iseed4"]),
            )

        weighted_events = run_dir / f"{tag}.wgt"
        if not weighted_events.exists() or weighted_events.stat().st_size == 0:
            raise campaign.RunError(f"cannot resume without non-empty weighted file: {weighted_events.name}")

        unweighted_events = run_dir / f"{tag}.unw"
        if not unweighted_events.exists():
            campaign.set_stage(manifest, None, run_index, tag, "alpgen_mode2")
            manifest["commands"].append(
                campaign.run_command_with_input(
                    [str(args.alpgen)],
                    mode2_input,
                    run_dir,
                    run_dir / f"{tag}_alpgen_mode2.stdout",
                    run_dir / f"{tag}_alpgen_mode2.stderr",
                    args.setup_command,
                )
            )

        unw_par = run_dir / f"{tag}_unw.par"
        alpgen_stats = campaign.parse_unw_par(unw_par)
        manifest["alpgen"] = alpgen_stats

        converted_lhe = run_dir / f"{tag}.lhe"
        if not converted_lhe.exists():
            campaign.set_stage(manifest, None, run_index, tag, "alpgentolh")
            manifest["commands"].append(
                campaign.run_command(
                    [str(args.alpgentolh), tag],
                    run_dir,
                    run_dir / f"{tag}_alpgentolh.stdout",
                    run_dir / f"{tag}_alpgentolh.stderr",
                )
            )

        input_events = campaign.count_lhe_events(converted_lhe)
        requested_herwig_events = campaign.choose_herwig_events(
            input_events,
            args.herwig_events,
            args.herwig_event_fraction,
        )
        manifest["events"] = {
            "converted_lhe": input_events,
            "requested_herwig": requested_herwig_events,
        }

        herwig_base = f"{tag}_Herwig"
        herwig_input = run_dir / f"{herwig_base}.in"
        correction_file = f"{herwig_base}.force8b.weights"
        if not herwig_input.exists():
            campaign.set_stage(
                manifest,
                None,
                run_index,
                tag,
                "herwig_prepare",
                f"{input_events} input events, requesting {requested_herwig_events}",
            )
            campaign.write_herwig_input(
                args.herwig_template,
                herwig_input,
                converted_lhe.name,
                herwig_base,
                correction_file,
                requested_herwig_events,
                manifest["seeds"]["herwig"],
            )
        manifest["files"]["herwig_input"] = campaign.rel(herwig_input)

        herwig_run_file = run_dir / f"{herwig_base}.run"
        if not herwig_run_file.exists():
            campaign.set_stage(manifest, None, run_index, tag, "herwig_read")
            manifest["commands"].append(
                campaign.run_command(
                    [args.herwig_command, "read", herwig_input.name],
                    run_dir,
                    run_dir / f"{tag}_herwig_read.stdout",
                    run_dir / f"{tag}_herwig_read.stderr",
                    args.setup_command,
                )
            )

        forced_lhe = run_dir / f"{herwig_base}.lhe"
        sidecar = run_dir / correction_file
        reweighted_lhe = run_dir / f"{herwig_base}-Reweighted.lhe"
        partial = False
        if not reweighted_lhe.exists():
            try:
                campaign.validate_forced_output_pair(forced_lhe, sidecar)
                partial = True
            except Exception:
                campaign.set_stage(manifest, None, run_index, tag, "herwig_run")
                herwig_run_result = campaign.run_command(
                    [args.herwig_command, "run", herwig_run_file.name],
                    run_dir,
                    run_dir / f"{tag}_herwig_run.stdout",
                    run_dir / f"{tag}_herwig_run.stderr",
                    args.setup_command,
                    check=False,
                )
                manifest["commands"].append(herwig_run_result)
                if herwig_run_result["returncode"] != 0:
                    herwig_error = campaign.command_failure_message(herwig_run_result)
                    manifest["herwig_run_error"] = herwig_error
                    manifest.setdefault("stage_history", []).append(
                        {
                            "stage": "herwig_run_error",
                            "timestamp": datetime.now().isoformat(),
                            "error": herwig_error,
                        }
                    )
                    if not args.salvage_failed_herwig:
                        raise campaign.RunError(herwig_error)
                    partial = True

            finalization = campaign.reweight_and_validate_forced_output(
                args,
                manifest,
                None,
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
        else:
            campaign.set_stage(manifest, None, run_index, tag, "validate")
            forced_events, sidecar_rows = campaign.validate_forced_output_pair(forced_lhe, sidecar)
            campaign.validate_lhe_declared_processes(reweighted_lhe)
            final_summary = campaign.parse_lhe_event_summary(reweighted_lhe)
            init_xsec = campaign.parse_init_xsec(reweighted_lhe)
            if final_summary["events"] != forced_events:
                raise campaign.RunError("existing reweighted LHE does not match forced LHE event count")
            if final_summary["bad_final_state_events"]:
                raise campaign.RunError(
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
                    "weighted_events": campaign.rel(weighted_events),
                    "unweighted_events": campaign.rel(unweighted_events),
                    "unweighted_parameters": campaign.rel(unw_par),
                    "converted_lhe": campaign.rel(converted_lhe),
                    "forced_lhe": campaign.rel(forced_lhe),
                    "force_sidecar": campaign.rel(sidecar),
                    "reweighted_lhe": campaign.rel(reweighted_lhe),
                }
            )
            finalization = {"final_summary": final_summary}

        manifest["status"] = "success_partial" if partial else "success"
        if partial:
            manifest["salvaged_partial_herwig"] = True
        if args.prune_herwig_intermediates:
            removed = campaign.prune_herwig_intermediates(run_dir, herwig_base)
            if removed:
                manifest.setdefault("pruned_files", []).extend(removed)
        manifest["current_stage"] = "complete"
        manifest.setdefault("stage_history", []).append(
            {"stage": "complete", "timestamp": datetime.now().isoformat()}
        )
        manifest["finished_at"] = datetime.now().isoformat()
        campaign.atomic_write_json(manifest_path, manifest)
        return manifest
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        manifest["current_stage"] = "failed"
        manifest.setdefault("stage_history", []).append(
            {"stage": "failed", "timestamp": datetime.now().isoformat(), "error": str(exc)}
        )
        manifest["finished_at"] = datetime.now().isoformat()
        campaign.atomic_write_json(manifest_path, manifest)
        raise


def campaign_summary(campaign_dir: Path) -> dict[str, Any]:
    manifests = [load_json(path) for path in sorted(campaign_dir.glob("run_*/run_manifest.json"))]
    usable = [item for item in manifests if item.get("status") in campaign.SUCCESS_STATUSES]
    failed = [item for item in manifests if item.get("status") not in campaign.SUCCESS_STATUSES]
    events = sum(int(item["events"]["final_reweighted"]) for item in usable)
    return {
        "manifests": len(manifests),
        "usable": len(usable),
        "failed": len(failed),
        "events": events,
        "events_per_usable": events / len(usable) if usable else 0.0,
    }


def next_run_index(campaign_dir: Path) -> int:
    indices = [run_index_from_dir(path) for path in campaign_dir.glob("run_*")]
    return max(indices, default=0) + 1


def run_existing_dirs(args: argparse.Namespace, run_dirs: list[Path]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        future_to_dir = {
            pool.submit(finish_existing_run, args, run_dir): run_dir
            for run_dir in run_dirs
        }
        for future in concurrent.futures.as_completed(future_to_dir):
            run_dir = future_to_dir[future]
            try:
                result = future.result()
                print(
                    f"[resume] {result['tag']} {result['status']} "
                    f"events={result.get('events', {}).get('final_reweighted')}",
                    flush=True,
                )
            except Exception as exc:
                result = {
                    "run_dir": campaign.rel(run_dir),
                    "status": "failed",
                    "error": str(exc),
                }
                print(f"[resume] {run_dir.name} failed error={exc}", flush=True)
            results.append(result)
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resume an interrupted 6Qg AlpGen -> Herwig forced 8b campaign."
    )
    parser.add_argument("campaign", help="Campaign name or campaign directory.")
    parser.add_argument("--target-events", type=int, default=None)
    parser.add_argument("--jobs", type=int, default=None)
    parser.add_argument("--batch-runs", type=int, default=None)
    parser.add_argument("--setup-command", default=None)
    parser.add_argument("--template", type=Path, default=None)
    parser.add_argument("--herwig-template", type=Path, default=None)
    parser.add_argument("--alpgen", type=Path, default=campaign.DEFAULT_ALPGEN)
    parser.add_argument("--alpgentolh", type=Path, default=campaign.DEFAULT_ALPGENTOLH)
    parser.add_argument("--reweight-script", type=Path, default=campaign.DEFAULT_REWEIGHT)
    parser.add_argument("--herwig-command", default="Herwig")
    parser.add_argument("--base-seed", type=int, default=12345)
    parser.add_argument("--herwig-seed-base", type=int, default=31122002)
    parser.add_argument("--herwig-events", default="all")
    parser.add_argument("--herwig-event-fraction", type=float, default=0.65)
    parser.add_argument("--salvage-failed-herwig", dest="salvage_failed_herwig", action="store_true", default=True)
    parser.add_argument("--no-salvage-failed-herwig", dest="salvage_failed_herwig", action="store_false")
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
    parser.add_argument("--progress-interval", type=float, default=15.0)
    parser.add_argument("--alpgen-progress-interval", type=float, default=5.0)
    parser.add_argument("--only-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def validate_args(args: argparse.Namespace) -> argparse.Namespace:
    args.campaign_dir = find_campaign_dir(args.campaign)
    if not args.campaign_dir.exists():
        raise FileNotFoundError(args.campaign_dir)
    top_manifest_path = args.campaign_dir / "campaign_manifest.json"
    top_manifest = load_json(top_manifest_path) if top_manifest_path.exists() else {}
    args.campaign = str(top_manifest.get("campaign") or args.campaign_dir.name)
    args.tag_prefix = str(top_manifest.get("tag_prefix") or args.campaign)
    args.target_events = args.target_events or top_manifest.get("target_events")
    args.jobs = args.jobs or int(top_manifest.get("jobs") or 32)
    args.batch_runs = args.batch_runs or args.jobs
    args.setup_command = args.setup_command if args.setup_command is not None else infer_setup_command(args.campaign_dir)

    source_template = args.template or find_first_source(args.campaign_dir, "_source_input_")
    source_herwig = args.herwig_template or find_first_source(args.campaign_dir, "_source_AlpGen8Q-LHEWriter.in")
    args.template = (source_template or campaign.DEFAULT_TEMPLATE).resolve()
    args.herwig_template = (source_herwig or campaign.DEFAULT_HERWIG_TEMPLATE).resolve()
    args.alpgen = args.alpgen.resolve()
    args.alpgentolh = args.alpgentolh.resolve()
    args.reweight_script = args.reweight_script.resolve()
    args.mode1_workload = campaign.parse_mode1_workload(args.template)

    if args.jobs < 1:
        raise ValueError("--jobs must be at least 1")
    if args.batch_runs < 1:
        raise ValueError("--batch-runs must be at least 1")
    for path in [args.template, args.herwig_template, args.alpgen, args.alpgentolh, args.reweight_script]:
        if not path.exists():
            raise FileNotFoundError(path)
    return args


def main() -> int:
    args = validate_args(build_arg_parser().parse_args())
    no_manifest_dirs = [
        run_dir for run_dir in sorted(args.campaign_dir.glob("run_*"))
        if not (run_dir / "run_manifest.json").exists()
    ]
    summary = campaign_summary(args.campaign_dir)
    print(
        "Campaign {campaign}: {events} events from {usable} usable runs; "
        "{failed} failed manifests; {pending} interrupted dirs".format(
            campaign=args.campaign,
            events=summary["events"],
            usable=summary["usable"],
            failed=summary["failed"],
            pending=len(no_manifest_dirs),
        )
    )
    print(f"Template: {args.template}")
    print(f"Herwig template: {args.herwig_template}")
    print(f"Setup command: {args.setup_command or '(none)'}")

    if args.dry_run:
        return 0

    if no_manifest_dirs:
        run_existing_dirs(args, no_manifest_dirs)
        manifest = salvage.rebuild_campaign_manifest(args.campaign_dir, args.merge)
        summary = campaign_summary(args.campaign_dir)
        print(
            f"After interrupted-run resume: {summary['events']} events "
            f"from {summary['usable']} usable runs"
        )
        if manifest.get("merge"):
            print(f"Merged LHE: {manifest['merge']['merged_lhe']}")

    if args.only_existing or args.target_events is None:
        return 0

    while True:
        summary = campaign_summary(args.campaign_dir)
        remaining = int(args.target_events) - int(summary["events"])
        if remaining <= 0:
            break
        estimate = max(1.0, summary["events_per_usable"] or 1.0)
        batch_size = min(args.batch_runs, max(1, math.ceil(remaining / estimate)))
        start_index = next_run_index(args.campaign_dir)
        run_indices = list(range(start_index, start_index + batch_size))
        print(
            f"Launching {len(run_indices)} new runs starting at {start_index} "
            f"to cover about {remaining} remaining events",
            flush=True,
        )
        batch_results = campaign.run_batch(args, run_indices)
        successes = [item for item in batch_results if item.get("status") in campaign.SUCCESS_STATUSES]
        salvage.rebuild_campaign_manifest(args.campaign_dir, args.merge)
        if not successes:
            raise campaign.RunError("new resume batch produced no successful runs")

    manifest = salvage.rebuild_campaign_manifest(args.campaign_dir, args.merge)
    print(f"Campaign manifest: {args.campaign_dir / 'campaign_manifest.json'}")
    if manifest.get("merge"):
        print(f"Merged LHE: {manifest['merge']['merged_lhe']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
