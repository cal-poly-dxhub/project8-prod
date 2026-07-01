import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["JOBS_TABLE"])


def handler(event, context):
    claims = event["requestContext"]["authorizer"]["claims"]
    user_id = claims["sub"]

    resp = table.query(
        IndexName="user-index",
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,
        Limit=50,
    )

    jobs = [{
        "job_id": item["job_id"],
        "filename": item["filename"],
        "status": item["status"],
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
    } for item in resp["Items"]]

    return {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps({"jobs": jobs}),
    }
