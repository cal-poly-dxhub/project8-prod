import json
import os
import boto3
from botocore.config import Config

# SigV4 + regional endpoint so the presigned URL points straight at the
# regional host (no 307 redirect that breaks browser CORS). See presigned_url.
_region = os.environ.get("AWS_REGION", "us-west-2")
s3 = boto3.client(
    "s3",
    region_name=_region,
    endpoint_url=f"https://s3.{_region}.amazonaws.com",
    config=Config(signature_version="s3v4"),
)
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["JOBS_TABLE"])
RESULTS_BUCKET = os.environ["RESULTS_BUCKET"]


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

    if item["status"] != "COMPLETED":
        return {
            "statusCode": 400,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "Job not completed yet"}),
        }

    results_key = item["results_key"]
    download_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": RESULTS_BUCKET, "Key": results_key},
        ExpiresIn=3600,
    )

    return {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps({"download_url": download_url}),
    }
