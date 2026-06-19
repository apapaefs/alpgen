#!/usr/bin/env python3
"""Salvage partial Herwig forced-8b output from an existing 6Qg campaign."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import run_6qg_8b_campaign as campaign


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def find_campaign_dir(value: str) -> Path:
    path = Path(value)
    if not path.exists():
        path = campaign.CAMPAIGNS_DIR / value
    return path.resolve()


def salvage_run(
    run_dir: Path,
    reweight_script: Path,
    dry_run: bool,
) -> dict[str, Any]:
    manifest_path = run_dir / "run_manifest.json"
    manifest = load_json(manifest_path)
    status = manifest.get("status")
    if status in campaign.SUCCESS_STATUSES:
        return {"run_dir": campaign.rel(run_dir), "status": "already_success"}

    tag = str(manifest["tag"])
    herwig_base = f"{tag}_Herwig"
    forced_lhe = run_dir / f"{herwig_base}.lhe"
    sidecar = run_dir / f"{herwig_base}.force8b.weights"
    reweighted_lhe = run_dir / f"{herwig_base}-Reweighted.lhe"

    try:
        forced_events, sidecar_rows = campaign.validate_forced_output_pair(
            forced_lhe, sidecar
        )
    except Exception as exc:
        return {
            "run_dir": campaign.rel(run_dir),
            "status": "not_salvageable",
            "reason": str(exc),
        }

    if dry_run:
        return {
            "run_dir": campaign.rel(run_dir),
            "status": "salvageable",
            "events": forced_events,
            "sidecar_rows": sidecar_rows,
        }

    original_status = manifest.get("status")
    original_error = manifest.get("error")
    manifest["original_status"] = original_status
    if original_error:
        manifest["original_error"] = original_error
        manifest["herwig_run_error"] = manifest.get("herwig_run_error", original_error)
    manifest.pop("error", None)

    tag_index = int(manifest["run_index"])
    unw_par = run_dir / f"{tag}_unw.par"
    converted_lhe = run_dir / f"{tag}.lhe"
    alpgen_stats = manifest.get("alpgen") or campaign.parse_unw_par(unw_par)
    manifest["alpgen"] = alpgen_stats
    manifest.setdefault("events", {})
    args = SimpleNamespace(reweight_script=reweight_script)
    finalization = campaign.reweight_and_validate_forced_output(
        args,
        manifest,
        None,
        tag_index,
        tag,
        run_dir,
        unw_par,
        converted_lhe,
        forced_lhe,
        sidecar,
        reweighted_lhe,
        alpgen_stats,
        herwig_base,
        partial=True,
    )
    manifest["status"] = "success_partial"
    manifest["salvaged_partial_herwig"] = True
    manifest["salvaged_at"] = datetime.now().isoformat()
    manifest["current_stage"] = "complete"
    manifest.setdefault("stage_history", []).append(
        {"stage": "complete", "timestamp": datetime.now().isoformat()}
    )
    manifest["finished_at"] = datetime.now().isoformat()
    campaign.atomic_write_json(manifest_path, manifest)

    return {
        "run_dir": campaign.rel(run_dir),
        "status": "salvaged",
        "events": int(finalization["final_summary"]["events"]),
    }


def rebuild_campaign_manifest(
    campaign_dir: Path,
    merge: bool,
) -> dict[str, Any]:
    manifest_path = campaign_dir / "campaign_manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
    else:
        manifest = {
            "campaign": campaign_dir.name,
            "tag_prefix": campaign_dir.name,
            "campaign_dir": campaign.rel(campaign_dir),
        }

    run_manifests = [
        load_json(path)
        for path in sorted(campaign_dir.glob("run_*/run_manifest.json"))
    ]
    successes = [item for item in run_manifests if item.get("status") in campaign.SUCCESS_STATUSES]
    failures = [item for item in run_manifests if item.get("status") not in campaign.SUCCESS_STATUSES]
    total_events = sum(int(item["events"]["final_reweighted"]) for item in successes)
    partial_successes = sum(1 for item in successes if item.get("status") == "success_partial")

    manifest["runs"] = run_manifests
    manifest["completed_events"] = total_events
    manifest["failed_runs"] = len(failures)
    manifest["partial_success_runs"] = partial_successes
    manifest["repaired_at"] = datetime.now().isoformat()
    target = manifest.get("target_events")
    target_met = target is None or total_events >= int(target)
    manifest["status"] = (
        "failed" if failures and not target_met
        else "success_with_failures" if failures
        else "success_with_partial" if partial_successes
        else "success"
    )

    if merge and successes:
        manifest["merge"] = campaign.merge_lhe(
            campaign_dir,
            str(manifest.get("campaign") or campaign_dir.name),
            run_manifests,
        )

    campaign.atomic_write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Salvage closed partial Herwig LHE files from failed 6Qg campaign runs."
    )
    parser.add_argument("campaign", help="Campaign name or campaign directory.")
    parser.add_argument(
        "--reweight-script",
        type=Path,
        default=campaign.DEFAULT_REWEIGHT,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--merge", dest="merge", action="store_true", default=True)
    parser.add_argument("--no-merge", dest="merge", action="store_false")
    args = parser.parse_args()

    campaign_dir = find_campaign_dir(args.campaign)
    if not campaign_dir.exists():
        raise FileNotFoundError(campaign_dir)
    reweight_script = args.reweight_script.resolve()
    if not reweight_script.exists():
        raise FileNotFoundError(reweight_script)

    results = [
        salvage_run(run_dir, reweight_script, args.dry_run)
        for run_dir in sorted(campaign_dir.glob("run_*"))
        if (run_dir / "run_manifest.json").exists()
    ]
    counts: dict[str, int] = {}
    events = 0
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        events += int(item.get("events") or 0)

    print(json.dumps({"campaign_dir": campaign.rel(campaign_dir), "counts": counts, "events": events}, indent=2))
    if not args.dry_run:
        manifest = rebuild_campaign_manifest(campaign_dir, args.merge)
        print(f"Campaign manifest: {campaign_dir / 'campaign_manifest.json'}")
        if manifest.get("merge"):
            print(f"Merged LHE: {manifest['merge']['merged_lhe']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
