#!/usr/bin/env python3
"""Migrate the OLD model's predictions + their legacy reviews into the new
integrated predictions table.

This is the July-6 cutover migration (step 4 / E in INTEGRATION_PLAN.md). It is
ADDITIVE and reads only from COPIES -- it never touches the live EC2 dashboard,
reviews.json, or any source data.

What it does, per the plan:
  1. Read the 12 interview_results/*.json snapshots (order preserved). Each
     interview's `claude_raw_output` is the ordered prediction list.
  2. Write one predictions-table row per annotation, tagged category="P8",
     SK = "{interview_id}#{idx}" where idx enumerates claude_raw_output in its
     ORIGINAL ORDER. This MUST match the legacy positional review key.
  3. Read reviews.json (keys like "Caregiver 11_49" = interview_id + "_" + idx),
     attach each reviewer's decision to the matching row, and recompute status
     via the 2-approval rule (>= 2 distinct approvers -> APPROVED).

CRITICAL: the review key is POSITIONAL. idx 49 of "Caregiver 11_49" is index 49
into Caregiver_11.json's claude_raw_output. We enumerate in that exact order so
reviews land on the right prediction (verified: Caregiver 11_49 -> Hypotonia).

Usage:
  # validate everything offline, write nothing:
  python migrate_legacy_data.py --snapshot ~/Downloads/p8-ec2-latest --dry-run

  # actually write into the deployed table (get the name from the stack output):
  python migrate_legacy_data.py --snapshot ~/Downloads/p8-ec2-latest \\
      --table P8IntegratedStack-PredictionsTableXXXX --category P8
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter

# Status machine. MUST match lambdas/vote/handler.py:_derive_status.
#   <2 votes -> PENDING; 2 agree -> APPROVED/REJECTED; 2 split -> CONFLICT;
#   3+ -> majority wins.
REVIEW_THRESHOLD = 2


def derive_status(approvals, rejections):
    n_appr = len(approvals)
    n_rej = len(rejections)
    total = n_appr + n_rej
    if total < REVIEW_THRESHOLD:
        return "PENDING"
    if n_rej == 0:
        return "APPROVED"
    if n_appr == 0:
        return "REJECTED"
    if total == 2:
        return "CONFLICT"
    return "APPROVED" if n_appr > n_rej else "REJECTED"


def load_interviews(snapshot_dir):
    """interview_id -> ordered list of annotation dicts (claude_raw_output)."""
    interviews = {}
    pattern = os.path.join(snapshot_dir, "interview_results", "*.json")
    for path in sorted(glob.glob(pattern)):
        with open(path) as f:
            d = json.load(f)
        interview_id = d["caregiver_id"]
        interviews[interview_id] = d["claude_raw_output"]
    return interviews


def load_reviews(snapshot_dir):
    with open(os.path.join(snapshot_dir, "reviews.json")) as f:
        return json.load(f)


def parse_review_key(key):
    """"Caregiver 11_49" -> ("Caregiver 11", 49). Splits on the LAST '_'."""
    interview_id, _, idx = key.rpartition("_")
    if not idx.isdigit():
        return None, None
    return interview_id, int(idx)


def build_rows(interviews, reviews, category):
    """Build every predictions-table row, with reviews attached.

    Returns (rows, stats). Raises nothing -- mismatches are collected in stats
    so a --dry-run surfaces them before any write happens.
    """
    stats = Counter()

    # Index reviews by (interview_id, idx) for attachment.
    reviews_by_key = {}
    for key, reviewer_map in reviews.items():
        interview_id, idx = parse_review_key(key)
        if interview_id is None:
            stats["unparseable_review_keys"] += 1
            continue
        reviews_by_key[(interview_id, idx)] = reviewer_map

    rows = []
    for interview_id, annotations in interviews.items():
        for idx, ann in enumerate(annotations):
            approvals = []
            rejections = []
            reviewer_map = reviews_by_key.pop((interview_id, idx), None)
            if reviewer_map:
                for reviewer, rev in reviewer_map.items():
                    decision = rev.get("decision")
                    ts = rev.get("timestamp")
                    if decision == "approve":
                        approvals.append({"reviewer": reviewer, "timestamp": ts})
                    elif decision == "reject":
                        rejections.append({
                            "reviewer": reviewer,
                            "timestamp": ts,
                            "reasons": rev.get("rejectionReasons", []) or [],
                            "comment": rev.get("comment", "") or "",
                            "suggested_concept_id": rev.get("suggestedConceptId"),
                        })
                    else:
                        stats["unknown_decision"] += 1
                stats["annotations_with_reviews"] += 1

            status = derive_status(approvals, rejections)
            stats[f"status_{status}"] += 1

            concept_id = ann.get("concept_id")
            row = {
                "category": category,
                "prediction_id": f"{interview_id}#{idx}",
                "interview_id": interview_id,
                "idx": idx,
                "source_job_id": "legacy-migration",
                "concept_id": str(concept_id) if concept_id is not None else None,
                "concept_name": ann.get("concept_name"),
                "quote": ann.get("raw_highlight"),
                "age": ann.get("age") or "n/a",
                "rationale": ann.get("rationale"),
                "caused_by": ann.get("caused_by") or [],
                "paragraph_id": ann.get("paragraph_id"),
                "status": status,
                "approvals": approvals,
                "rejections": rejections,
                "review_count": len(approvals) + len(rejections),
                "version": 0,
            }
            # DynamoDB rejects empty-string values; drop them.
            row = {k: v for k, v in row.items() if v != ""}
            rows.append(row)
            stats["rows"] += 1

    # Any review key that never matched a prediction is a data problem -- the
    # plan's whole correctness hinge is that every review attaches.
    stats["unmatched_reviews"] = len(reviews_by_key)
    if reviews_by_key:
        for key in list(reviews_by_key)[:20]:
            print(f"  UNMATCHED REVIEW: {key[0]}#{key[1]}", file=sys.stderr)

    return rows, stats


def write_rows(rows, table_name):
    import boto3
    # Region resolves from AWS_REGION/AWS_DEFAULT_REGION, else falls back to the
    # stack's default so the script works even when the env var is unset.
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    with table.batch_writer() as batch:
        for row in rows:
            batch.put_item(Item=row)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--snapshot", required=True,
                   help="dir holding interview_results/ and reviews.json")
    p.add_argument("--category", default="P8", help="category label for all rows")
    p.add_argument("--table", help="predictions table name (required unless --dry-run)")
    p.add_argument("--dry-run", action="store_true",
                   help="validate + report only, write nothing, no AWS calls")
    args = p.parse_args()

    interviews = load_interviews(args.snapshot)
    reviews = load_reviews(args.snapshot)
    print(f"Loaded {len(interviews)} interviews, {len(reviews)} reviewed annotations")

    rows, stats = build_rows(interviews, reviews, args.category)

    print("\n=== migration summary ===")
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")

    if stats["unmatched_reviews"] or stats["unparseable_review_keys"]:
        print("\nERROR: some reviews did not attach to a prediction. "
              "Fix before writing.", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("\n[dry-run] no rows written.")
        return

    if not args.table:
        print("ERROR: --table is required unless --dry-run", file=sys.stderr)
        sys.exit(2)

    print(f"\nWriting {len(rows)} rows to {args.table} ...")
    write_rows(rows, args.table)
    print("Done.")


if __name__ == "__main__":
    main()
