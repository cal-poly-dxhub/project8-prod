import json
import os
import uuid
import time
import boto3
from botocore.config import Config

# Force SigV4 + the regional endpoint. The default (SigV2 against the global
# s3.amazonaws.com host) makes S3 return a 307 redirect to the regional host
# for buckets outside us-east-1. curl follows that, but a browser fetch PUT
# does not -- and the redirect carries no CORS headers, so the browser upload
# fails with "TypeError: Failed to fetch".
_region = os.environ.get("AWS_REGION", "us-west-2")
s3 = boto3.client(
    "s3",
    region_name=_region,
    endpoint_url=f"https://s3.{_region}.amazonaws.com",
    config=Config(signature_version="s3v4"),
)
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["JOBS_TABLE"])
UPLOADS_BUCKET = os.environ["UPLOADS_BUCKET"]
# Present only in the integrated stack. When set, an uploaded interview's
# category is recorded here so "choose existing or create new" stays in sync.
CATEGORIES_TABLE = os.environ.get("CATEGORIES_TABLE")


def _parse_age(raw):
    """Normalize an optional age input to a non-negative int, or None.

    Accepts numbers or numeric strings; anything blank/invalid/out-of-range is
    treated as "not provided" so the field stays optional and never blocks an
    upload.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        age = int(float(raw))
    except (TypeError, ValueError):
        return None
    if 0 <= age <= 120:
        return age
    return None


def handler(event, context):
    body = json.loads(event["body"])
    filename = body["filename"]
    # Category is optional for backward compat (the original stack sends none).
    # The category is stored on the job record, NOT in the S3 key, so the
    # worker's key parsing is unchanged -- the worker reads it back by job_id.
    category = (body.get("category") or "").strip()
    # Optional interviewee age at the time of THIS interview (distinct from the
    # per-annotation `age`, which is the age at which a described event happened).
    # Stored on the job record and later stamped onto every prediction row so the
    # visualizations can break concepts down by age.
    interview_age = _parse_age(body.get("interview_age"))

    claims = event["requestContext"]["authorizer"]["claims"]
    user_id = claims["sub"]

    job_id = str(uuid.uuid4())
    s3_key = f"uploads/{job_id}/{filename}"

    presigned_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": UPLOADS_BUCKET, "Key": s3_key, "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ExpiresIn=300,
    )

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ttl = int(time.time()) + 30 * 24 * 3600  # 30 days

    item = {
        "job_id": job_id,
        "user_id": user_id,
        "filename": filename,
        "status": "UPLOADING",
        "s3_key": s3_key,
        "created_at": now,
        "updated_at": now,
        "ttl": ttl,
    }
    if category:
        item["category"] = category
    if interview_age is not None:
        item["interview_age"] = interview_age
    table.put_item(Item=item)

    # Register the category (idempotent) so it shows up in the dropdown later.
    if category and CATEGORIES_TABLE:
        cat_table = dynamodb.Table(CATEGORIES_TABLE)
        try:
            cat_table.put_item(
                Item={"category": category, "created_by": user_id, "created_at": now},
                ConditionExpression="attribute_not_exists(category)",
            )
        except cat_table.meta.client.exceptions.ConditionalCheckFailedException:
            pass  # category already exists, leave it as-is

    return {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps({"job_id": job_id, "upload_url": presigned_url}),
    }
