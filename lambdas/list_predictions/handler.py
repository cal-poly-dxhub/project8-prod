import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
predictions_table = dynamodb.Table(os.environ["PREDICTIONS_TABLE"])

CORS = {"Access-Control-Allow-Origin": "*"}


def _resp(status, body):
    return {"statusCode": status, "headers": CORS, "body": json.dumps(body, default=str)}


def _redact_for_blind_review(item, reviewer):
    """Blind review: a reviewer can't see others' votes until they vote on this
    prediction. We always expose review_count + caller_voted (needed for queue
    state), but only reveal the approvals/rejections detail once the caller has
    voted. Status is downgraded to PENDING in the response while still blind so
    the aggregate outcome doesn't leak either.
    """
    approvals = item.get("approvals", []) or []
    rejections = item.get("rejections", []) or []
    voters = {v.get("reviewer") for v in approvals} | {v.get("reviewer") for v in rejections}
    caller_voted = reviewer in voters

    item["review_count"] = len(approvals) + len(rejections)
    item["caller_voted"] = caller_voted
    if not caller_voted:
        # Hide who voted and which way, and don't leak the settled outcome.
        item.pop("approvals", None)
        item.pop("rejections", None)
        if item.get("status") in ("APPROVED", "REJECTED", "CONFLICT"):
            item["status"] = "PENDING"
    return item


def handler(event, context):
    # Query predictions for a category. Two modes:
    #   GET /predictions?category=P8                      -> all rows in category
    #   GET /predictions?category=P8&interview=Caregiver 11 -> one interview
    #   GET /predictions?category=P8&status=PENDING       -> filter by status (GSI)
    # Each row is redacted for blind review based on the caller's Cognito sub.
    params = event.get("queryStringParameters") or {}
    category = (params.get("category") or "").strip()
    status = (params.get("status") or "").strip()
    interview = (params.get("interview") or "").strip()
    if not category:
        return _resp(400, {"message": "category query param is required"})

    claims = (event.get("requestContext", {}).get("authorizer", {}) or {}).get("claims", {}) or {}
    reviewer = claims.get("sub", "")

    if interview:
        # SK is "interview_id#idx"; prefix-match to get one interview's rows.
        resp = predictions_table.query(
            KeyConditionExpression=Key("category").eq(category)
            & Key("prediction_id").begins_with(f"{interview}#"),
        )
    elif status:
        resp = predictions_table.query(
            IndexName="category-status-index",
            KeyConditionExpression=Key("category").eq(category) & Key("status").eq(status),
        )
    else:
        resp = predictions_table.query(
            KeyConditionExpression=Key("category").eq(category),
        )

    items = [_redact_for_blind_review(it, reviewer) for it in resp.get("Items", [])]
    # Sort by interview then position so the review screen can step in order.
    items.sort(key=lambda it: (it.get("interview_id", ""), it.get("idx", 0)))
    return _resp(200, {"predictions": items})
