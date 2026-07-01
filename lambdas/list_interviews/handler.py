import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
predictions_table = dynamodb.Table(os.environ["PREDICTIONS_TABLE"])

CORS = {"Access-Control-Allow-Origin": "*"}


def _resp(status, body):
    return {"statusCode": status, "headers": CORS, "body": json.dumps(body, default=str)}


def handler(event, context):
    # GET /interviews?category=P8 -> list of interviews in the category with
    # per-interview review progress, so the review screen can show a pick list.
    params = event.get("queryStringParameters") or {}
    category = (params.get("category") or "").strip()
    if not category:
        return _resp(400, {"message": "category query param is required"})

    # Paginate the full category partition (one row per prediction).
    items = []
    kwargs = {"KeyConditionExpression": Key("category").eq(category),
              "ProjectionExpression": "interview_id, #s, approvals, rejections",
              "ExpressionAttributeNames": {"#s": "status"}}
    while True:
        resp = predictions_table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    interviews = {}
    for it in items:
        iid = it.get("interview_id", "")
        agg = interviews.setdefault(
            iid, {"interview_id": iid, "total": 0, "approved": 0, "rejected": 0,
                  "conflict": 0, "pending": 0, "reviewed": 0}
        )
        agg["total"] += 1
        st = it.get("status", "PENDING")
        if st == "APPROVED":
            agg["approved"] += 1
        elif st == "REJECTED":
            agg["rejected"] += 1
        elif st == "CONFLICT":
            agg["conflict"] += 1
        else:
            agg["pending"] += 1
        # "reviewed" = at least 2 votes recorded (settled or in conflict).
        n_votes = len(it.get("approvals", []) or []) + len(it.get("rejections", []) or [])
        if n_votes >= 2:
            agg["reviewed"] += 1

    result = sorted(interviews.values(), key=lambda a: a["interview_id"])
    return _resp(200, {"interviews": result})
