import json
import os
import time
import boto3

dynamodb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")
s3 = boto3.client("s3")

table = dynamodb.Table(os.environ["JOBS_TABLE"])
QUEUE_URL = os.environ["QUEUE_URL"]
UPLOADS_BUCKET = os.environ["UPLOADS_BUCKET"]


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body),
    }


def handler(event, context):
    """Resolve a job paused in PII_REVIEW.

    decision=proceed  -> acknowledge the findings, re-enqueue the job (the
                         worker skips the scan when pii_acknowledged is set).
    decision=cancel   -> delete the upload and mark the job CANCELLED.
    """
    job_id = event["pathParameters"]["id"]
    claims = event["requestContext"]["authorizer"]["claims"]
    user_id = claims["sub"]
    body = json.loads(event.get("body") or "{}")
    decision = body.get("decision")

    item = table.get_item(Key={"job_id": job_id}).get("Item")
    if not item or item.get("user_id") != user_id:
        return _resp(404, {"error": "Job not found"})
    if item.get("status") != "PII_REVIEW":
        return _resp(409, {"error": f"Job is not awaiting PII review (status={item.get('status')})"})

    s3_key = item["s3_key"]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if decision == "proceed":
        table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s, updated_at = :u, pii_acknowledged = :a",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "PROCESSING", ":u": now, ":a": True},
        )
        # Re-enqueue using the same S3-event shape the worker already parses, so
        # the worker needs no special-casing to pick the job back up.
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                "Records": [{"s3": {
                    "bucket": {"name": UPLOADS_BUCKET},
                    "object": {"key": s3_key},
                }}]
            }),
        )
        return _resp(200, {"job_id": job_id, "status": "PROCESSING"})

    if decision == "cancel":
        try:
            s3.delete_object(Bucket=UPLOADS_BUCKET, Key=s3_key)
        except Exception as e:
            print(f"Job {job_id}: could not delete cancelled upload: {e}")
        table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s, updated_at = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "CANCELLED", ":u": now},
        )
        return _resp(200, {"job_id": job_id, "status": "CANCELLED"})

    return _resp(400, {"error": "decision must be 'proceed' or 'cancel'"})
