import json
import os
import time
import boto3

dynamodb = boto3.resource("dynamodb")
categories_table = dynamodb.Table(os.environ["CATEGORIES_TABLE"])

CORS = {"Access-Control-Allow-Origin": "*"}


def _resp(status, body):
    return {"statusCode": status, "headers": CORS, "body": json.dumps(body)}


def handler(event, context):
    method = event.get("httpMethod", "GET")

    if method == "GET":
        # List all categories, alphabetical.
        items = categories_table.scan().get("Items", [])
        names = sorted(item["category"] for item in items)
        return _resp(200, {"categories": names})

    if method == "POST":
        body = json.loads(event.get("body") or "{}")
        name = (body.get("category") or "").strip()
        if not name:
            return _resp(400, {"message": "category is required"})

        claims = event["requestContext"]["authorizer"]["claims"]
        created_by = claims.get("sub", "unknown")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Idempotent create: attribute_not_exists keeps an existing category
        # (and its created_at) intact rather than overwriting it.
        try:
            categories_table.put_item(
                Item={"category": name, "created_by": created_by, "created_at": now},
                ConditionExpression="attribute_not_exists(category)",
            )
        except categories_table.meta.client.exceptions.ConditionalCheckFailedException:
            return _resp(200, {"category": name, "created": False})
        return _resp(201, {"category": name, "created": True})

    return _resp(405, {"message": f"method {method} not allowed"})
