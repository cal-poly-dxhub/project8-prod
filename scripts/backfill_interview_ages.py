#!/usr/bin/env python3
"""Backfill interview_age onto EXISTING prediction rows in the integrated table.

The legacy migration (migrate_legacy_data.py) ran before the age feature existed,
so those rows have no interview_age. This script stamps the interviewee's age
(from the Round 1 Disease Concept spreadsheet) onto every prediction row whose
interview_id has a known age. It is idempotent and only touches the age field.

Usage:
  # preview what would change, write nothing:
  python backfill_interview_ages.py --table P8IntegratedStack-PredictionsTableXXXX \\
      --category P8 --dry-run

  # actually update the rows:
  python backfill_interview_ages.py --table P8IntegratedStack-PredictionsTableXXXX \\
      --category P8
"""
import argparse
import os
import sys

from boto3.dynamodb.conditions import Key

# Reuse the single source of truth for the ages.
sys.path.insert(0, os.path.dirname(__file__))
from migrate_legacy_data import LEGACY_INTERVIEW_AGES


def _dynamodb():
    import boto3
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
    return boto3.resource("dynamodb", region_name=region)


def query_all(table, category):
    items = []
    kwargs = {"KeyConditionExpression": Key("category").eq(category)}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--table", required=True, help="predictions table name")
    p.add_argument("--category", default="P8", help="category to backfill")
    p.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = p.parse_args()

    table = _dynamodb().Table(args.table)
    rows = query_all(table, args.category)
    print(f"Scanned {len(rows)} rows in category '{args.category}'")

    to_update = []
    skipped_no_age = 0
    already = 0
    for r in rows:
        age = LEGACY_INTERVIEW_AGES.get(r.get("interview_id"))
        if age is None:
            skipped_no_age += 1
            continue
        if r.get("interview_age") is not None and int(r["interview_age"]) == age:
            already += 1
            continue
        to_update.append((r["category"], r["prediction_id"], age))

    print(f"  to update: {len(to_update)}")
    print(f"  already correct: {already}")
    print(f"  no known age (unchanged): {skipped_no_age}")

    if args.dry_run:
        print("\n[dry-run] no rows written.")
        return

    for category, prediction_id, age in to_update:
        table.update_item(
            Key={"category": category, "prediction_id": prediction_id},
            UpdateExpression="SET interview_age = :a",
            ExpressionAttributeValues={":a": age},
        )
    print(f"\nUpdated {len(to_update)} rows.")


if __name__ == "__main__":
    main()
