import json
import os
import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["JOBS_TABLE"])


def handler(event, context):
    job_id = event["pathParameters"]["id"]
    claims = event["requestContext"]["authorizer"]["claims"]
    user_id = claims["sub"]

    resp = table.get_item(Key={"job_id": job_id})
    item = resp.get("Item")

    if not item or item["user_id"] != user_id:
        return {
            "statusCode": 404,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "Job not found"}),
        }

    return {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps({
            "job_id": item["job_id"],
            "filename": item["filename"],
            "status": item["status"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "error_message": item.get("error_message"),
            "pii_findings": item.get("pii_findings"),
        }, default=str),
    }
