import json
import os
import time
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
predictions_table = dynamodb.Table(os.environ["PREDICTIONS_TABLE"])

CORS = {"Access-Control-Allow-Origin": "*"}

# A prediction is settled once this many distinct reviewers have voted.
REVIEW_THRESHOLD = 2


def _resp(status, body):
    return {"statusCode": status, "headers": CORS, "body": json.dumps(body, default=str)}


def _derive_status(approvals, rejections):
    # Status machine (matches the review model the user confirmed):
    #   - fewer than 2 votes              -> PENDING  (assumed correct until reviewed)
    #   - 2 votes, both agree (approve)   -> APPROVED
    #   - 2 votes, both agree (reject)    -> REJECTED
    #   - 2 votes, 1 approve vs 1 reject  -> CONFLICT (needs a 3rd reviewer)
    #   - 3+ votes                        -> majority wins (tie-break)
    n_appr = len(approvals)
    n_rej = len(rejections)
    total = n_appr + n_rej

    if total < REVIEW_THRESHOLD:
        return "PENDING"
    if n_rej == 0:
        return "APPROVED"
    if n_appr == 0:
        return "REJECTED"
    # Mixed votes: a 2-person split is an unresolved conflict; once a 3rd (or
    # more) reviewer weighs in, the majority decision settles it.
    if total == 2:
        return "CONFLICT"
    return "APPROVED" if n_appr > n_rej else "REJECTED"


def handler(event, context):
    # POST /predictions/{id}/vote   body: {category, decision, reasons?, comment?}
    # {id} is the prediction_id (the sort key, e.g. "Caregiver 11#49").
    path_params = event.get("pathParameters") or {}
    prediction_id = path_params.get("id")
    body = json.loads(event.get("body") or "{}")
    category = (body.get("category") or "").strip()
    decision = (body.get("decision") or "").strip().lower()

    if not prediction_id or not category:
        return _resp(400, {"message": "category and prediction id are required"})
    if decision not in ("approve", "reject"):
        return _resp(400, {"message": "decision must be 'approve' or 'reject'"})

    claims = event["requestContext"]["authorizer"]["claims"]
    reviewer = claims.get("sub", "unknown")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Read-modify-write with optimistic concurrency. We retry on a version
    # mismatch so concurrent votes on the same prediction don't clobber.
    for _ in range(5):
        item = predictions_table.get_item(
            Key={"category": category, "prediction_id": prediction_id}
        ).get("Item")
        if not item:
            return _resp(404, {"message": "prediction not found"})

        approvals = {a["reviewer"]: a for a in item.get("approvals", [])}
        rejections = {r["reviewer"]: r for r in item.get("rejections", [])}

        # One vote per reviewer: a new vote replaces this reviewer's prior one
        # in either list.
        approvals.pop(reviewer, None)
        rejections.pop(reviewer, None)
        if decision == "approve":
            approvals[reviewer] = {"reviewer": reviewer, "timestamp": now}
        else:
            rejections[reviewer] = {
                "reviewer": reviewer,
                "timestamp": now,
                "reasons": body.get("reasons", []),
                "comment": body.get("comment", ""),
                "suggested_concept_id": body.get("suggested_concept_id"),
                "no_relevant_concept": bool(body.get("no_relevant_concept", False)),
            }

        approvals_list = list(approvals.values())
        rejections_list = list(rejections.values())
        new_status = _derive_status(approvals_list, rejections_list)
        version = item.get("version", 0)

        try:
            predictions_table.update_item(
                Key={"category": category, "prediction_id": prediction_id},
                UpdateExpression=(
                    "SET approvals = :a, rejections = :r, #s = :s, "
                    "review_count = :rc, version = :nv, updated_at = :u"
                ),
                ConditionExpression="attribute_not_exists(version) OR version = :v",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":a": approvals_list,
                    ":r": rejections_list,
                    ":s": new_status,
                    ":rc": len(approvals_list) + len(rejections_list),
                    ":nv": version + 1,
                    ":v": version,
                    ":u": now,
                },
            )
            return _resp(200, {
                "prediction_id": prediction_id,
                "status": new_status,
                "approvals": len(approvals_list),
                "rejections": len(rejections_list),
            })
        except predictions_table.meta.client.exceptions.ConditionalCheckFailedException:
            continue  # someone else voted; re-read and retry

    return _resp(409, {"message": "vote conflict, please retry"})
