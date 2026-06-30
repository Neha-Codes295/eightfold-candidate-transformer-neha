#!/usr/bin/env python3
"""
candidate-transformer: merge candidate data from CSV, ATS JSON, and GitHub
into canonical JSON profiles.

Usage:
  python main.py --csv sample_inputs/candidates.csv \
                 --ats sample_inputs/ats.json \
                 --github torvalds \
                 --github octocat \
                 --config config.json \
                 --output output.json
"""
import argparse
import json
import sys
from pathlib import Path

from pipeline.extract import extract_csv, extract_ats, extract_github
from pipeline.normalize import normalize_record
from pipeline.merge import merge_all
from pipeline.confidence import compute_confidence
from pipeline.project import apply_projection, MissingFieldError
from pipeline.validate import validate_output


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run(args: argparse.Namespace) -> int:
    warnings: list[str] = []
    all_records = []

    # --- Extract ---
    if args.csv:
        for csv_path in args.csv:
            records = extract_csv(csv_path, warnings)
            all_records.extend(records)

    if args.ats:
        for ats_path in args.ats:
            records = extract_ats(ats_path, warnings)
            all_records.extend(records)

    if args.github:
        for gh in args.github:
            records = extract_github(gh, warnings)
            all_records.extend(records)

    if not all_records:
        print("ERROR: No records extracted from any source.", file=sys.stderr)
        _print_warnings(warnings)
        return 1

    # --- Normalize ---
    for rec in all_records:
        normalize_record(rec, warnings)

    # --- Merge ---
    merged_list = merge_all(all_records)

    # --- Confidence ---
    for merged in merged_list:
        compute_confidence(merged)

    # --- Load config (optional) ---
    config = None
    if args.config:
        try:
            config = load_config(args.config)
        except FileNotFoundError:
            warnings.append(f"Config file not found: {args.config}; using default schema")
        except json.JSONDecodeError as exc:
            warnings.append(f"Config JSON parse error: {exc}; using default schema")

    # --- Project + Validate ---
    output_list = []
    for merged in merged_list:
        try:
            projected = apply_projection(merged, config)
        except MissingFieldError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            _print_warnings(warnings)
            return 1

        validated = validate_output(projected, warnings, is_projected=(config is not None))
        output_list.append(validated)

    # --- Sort for determinism ---
    output_list.sort(key=lambda c: c.get("candidate_id") or c.get("full_name") or "")

    # --- Output ---
    output_json = json.dumps(output_list, indent=2, ensure_ascii=False)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_json, encoding="utf-8")
        print(f"Wrote {len(output_list)} candidate(s) to {args.output}")
    else:
        print(output_json)

    _print_warnings(warnings)
    return 0


def _print_warnings(warnings: list) -> None:
    if warnings:
        print("\n--- Warnings ---", file=sys.stderr)
        for w in warnings:
            print(f"  [WARN] {w}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Merge candidate data from CSV, ATS JSON, and GitHub into canonical JSON."
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        action="append",
        help="Path to candidates CSV file (repeatable)",
    )
    parser.add_argument(
        "--ats",
        metavar="PATH",
        action="append",
        help="Path to ATS JSON file (repeatable)",
    )
    parser.add_argument(
        "--github",
        metavar="USERNAME_OR_URL",
        action="append",
        help="GitHub username or profile URL (repeatable)",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to projection config JSON (optional; omit for full canonical output)",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write JSON output to this file (optional; default: stdout)",
    )

    args = parser.parse_args()

    if not any([args.csv, args.ats, args.github]):
        parser.print_help()
        print("\nERROR: Provide at least one of --csv, --ats, --github", file=sys.stderr)
        sys.exit(1)

    sys.exit(run(args))


if __name__ == "__main__":
    main()
