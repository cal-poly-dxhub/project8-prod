import json
import os
import boto3
from collections import defaultdict
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
predictions_table = dynamodb.Table(os.environ["PREDICTIONS_TABLE"])

CORS = {"Access-Control-Allow-Origin": "*"}

# Bundled codebook metadata: code_id (str) -> {name, type, depth, category,
# category_color, domain}. Built from the dashboard's concept_frequency.json
# (clean category/domain/color mapping) plus the raw codebook for full coverage.
_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "codebook_meta.json")) as _f:
    CODEBOOK = json.load(_f)


def _resp(status, body):
    return {"statusCode": status, "headers": CORS, "body": json.dumps(body, default=str)}


def _query_all(category):
    """Return every prediction row in a category (paginated)."""
    items = []
    kwargs = {"KeyConditionExpression": Key("category").eq(category)}
    while True:
        resp = predictions_table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def handler(event, context):
    # GET /aggregate?category=X
    # Builds the three data shapes the visualizations consume, applying the
    # "counts until rejected" rule: every prediction is included UNLESS its
    # status is REJECTED. The pipeline output is assumed correct until a human
    # rejects it, so PENDING/APPROVED/CONFLICT all count.
    params = event.get("queryStringParameters") or {}
    category = (params.get("category") or "").strip()
    if not category:
        return _resp(400, {"message": "category query param is required"})

    rows = _query_all(category)

    # caregivers[]: one entry per interview, expected = distinct non-rejected
    # concept ids mentioned in that interview.
    by_interview = defaultdict(set)
    # quotes_by_concept: code_id (str) -> [{quote, caregiver, age}] (deduped)
    quotes_by_concept = defaultdict(list)
    # concept counting: code_id (str) -> set of interview ids
    concept_caregivers = defaultdict(set)
    # first quote seen per concept, for the bar-chart hover preview
    concept_quote = {}

    for r in rows:
        if r.get("status") == "REJECTED":
            continue
        cid = r.get("concept_id")
        if cid is None:
            continue
        cid = str(cid)
        interview = r.get("interview_id") or ""
        quote = (r.get("quote") or "").strip()
        age = r.get("age") or None

        by_interview[interview].add(cid)
        concept_caregivers[cid].add(interview)

        if quote:
            dup = any(q["caregiver"] == interview and q["quote"] == quote
                      for q in quotes_by_concept[cid])
            if not dup:
                quotes_by_concept[cid].append({"quote": quote, "caregiver": interview, "age": age})
            if cid not in concept_quote:
                concept_quote[cid] = {"quote": quote, "quote_caregiver": interview, "quote_age": age}

    n_interviews = len(by_interview)

    caregivers = []
    for interview in sorted(by_interview):
        expected = sorted(by_interview[interview], key=lambda x: int(x) if x.isdigit() else x)
        caregivers.append({
            "caregiver_id": interview,
            "filename": interview,
            "timestamp": None,
            "expected": expected,
            "predicted": expected,
        })

    # concept_frequency[]: one entry per concept that appears in this category,
    # joined with the bundled codebook metadata.
    concept_frequency = []
    for cid, interviews in concept_caregivers.items():
        meta = CODEBOOK.get(cid)
        if not meta:
            # Concept not in the codebook (shouldn't happen) -- emit minimal row.
            meta = {
                "code_id": int(cid) if cid.isdigit() else cid,
                "name": f"Concept {cid}",
                "type": "Concept",
                "depth": 2.0,
                "category": "MODIFYING FACTORS",
                "category_color": "#999999",
                "domain": "Other",
            }
        count = len(interviews)
        q = concept_quote.get(cid, {})
        concept_frequency.append({
            "code_id": meta["code_id"],
            "name": meta["name"],
            "type": meta.get("type", "Concept"),
            "depth": meta.get("depth", 2.0),
            "category": meta["category"],
            "category_color": meta["category_color"],
            "domain": meta["domain"],
            "caregiver_count": count,
            "pct": round(count / n_interviews * 100) if n_interviews else 0,
            "caregivers": sorted(interviews),
            "quote": q.get("quote"),
            "quote_caregiver": q.get("quote_caregiver"),
            "quote_age": q.get("quote_age"),
        })

    return _resp(200, {
        "category": category,
        "n_interviews": n_interviews,
        "caregivers": caregivers,
        "concept_frequency": concept_frequency,
        "quotes_by_concept": dict(quotes_by_concept),
    })
