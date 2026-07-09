import asyncio
import json
import os
import time
import traceback
import urllib.parse
import boto3

sqs = boto3.client("sqs")
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["JOBS_TABLE"])

QUEUE_URL = os.environ["QUEUE_URL"]
UPLOADS_BUCKET = os.environ["UPLOADS_BUCKET"]
RESULTS_BUCKET = os.environ["RESULTS_BUCKET"]
# Present only in the integrated stack. When set, each annotation is also
# written as a row in the predictions table tagged with the job's category.
PREDICTIONS_TABLE = os.environ.get("PREDICTIONS_TABLE")
# Guardrail used ONLY for the upload-time direct-identifier scan (never to
# block model calls). Absent on local runs, which skip the scan.
BEDROCK_GUARDRAIL_ID = os.environ.get("BEDROCK_GUARDRAIL_ID")
BEDROCK_GUARDRAIL_VERSION = os.environ.get("BEDROCK_GUARDRAIL_VERSION")


def update_job_status(job_id, status, error_message=None, results_key=None, pii_findings=None):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    update_expr = "SET #s = :s, updated_at = :u"
    expr_values = {":s": status, ":u": now}
    expr_names = {"#s": "status"}

    if error_message:
        update_expr += ", error_message = :e"
        expr_values[":e"] = error_message
    if results_key:
        update_expr += ", results_key = :r"
        expr_values[":r"] = results_key
    if pii_findings is not None:
        update_expr += ", pii_findings = :p"
        expr_values[":p"] = pii_findings

    table.update_item(
        Key={"job_id": job_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


def write_prediction_rows(job_id, category, interview_id, annotations, interview_age=None, hero_id=None):
    """Write each annotation as a row in the predictions table.

    PK = category, SK = "{interview_id}#{idx}" where idx enumerates the
    annotations in their ORIGINAL ORDER. This matches the legacy positional
    review key convention ("Caregiver 11_49") so migrated reviews attach to the
    right prediction. Each row starts PENDING with empty vote lists.
    """
    if not (PREDICTIONS_TABLE and category):
        return

    predictions_table = dynamodb.Table(PREDICTIONS_TABLE)
    with predictions_table.batch_writer() as batch:
        for idx, ann in enumerate(annotations):
            prediction_id = f"{interview_id}#{idx}"
            item = {
                "category": category,
                "prediction_id": prediction_id,
                "interview_id": interview_id,
                "idx": idx,
                "source_job_id": job_id,
                "concept_id": str(ann.get("concept_id")) if ann.get("concept_id") is not None else None,
                "concept_name": ann.get("concept_name"),
                "quote": ann.get("raw_highlight"),
                "age": ann.get("age") or "n/a",
                "rationale": ann.get("rationale"),
                "caused_by": ann.get("caused_by") or [],
                "paragraph_id": ann.get("paragraph_id"),
                "status": "PENDING",
                "approvals": [],
                "rejections": [],
                "review_count": 0,
                "version": 0,
            }
            # Interviewee's age at interview time (optional). Stamped on every
            # row so the visualizations can group concepts by age without a join.
            if interview_age is not None:
                item["interview_age"] = interview_age
            # Hero id (optional): the interviewee identifier, stamped on every
            # row so the visualizations can group a hero's interviews across
            # ages for longitudinal / comorbidity analysis.
            if hero_id:
                item["hero_id"] = hero_id
            # DynamoDB rejects empty-string values; drop them.
            item = {k: v for k, v in item.items() if v != ""}
            batch.put_item(Item=item)


async def process_job(job_id, s3_key, filename):
    from utils.parsers import parse_docx_files
    from utils.annotation_engine import annotate_with_multi_pass_claude
    from utils.pii_scan import scan_for_direct_identifiers
    from config import NUM_PASSES

    # Read the category off the job record (set by the upload lambda). The
    # category lives on the record, not the S3 key, so key parsing is unchanged.
    job_record = table.get_item(Key={"job_id": job_id}).get("Item") or {}
    category = job_record.get("category")
    # Optional interviewee age at interview time. DynamoDB returns numbers as
    # Decimal; coerce to a plain int for the prompt line and the prediction rows.
    interview_age = job_record.get("interview_age")
    if interview_age is not None:
        interview_age = int(interview_age)
    # Optional hero id: a free-form interviewee identifier the customer maintains.
    # Not validated; stamped onto every prediction row for longitudinal grouping.
    hero_id = job_record.get("hero_id")

    local_path = f"/tmp/{filename}"
    s3.download_file(UPLOADS_BUCKET, s3_key, local_path)

    update_job_status(job_id, "PROCESSING")

    with open(local_path, "rb") as f:
        parsed_docs = parse_docx_files([f])

    # PII gate: scan the transcript for DIRECT identifiers (names, SSNs, etc --
    # NOT age) before it reaches the model. Detections do NOT hard-block, since
    # real transcripts naturally contain names/addresses. Instead we PAUSE the
    # job in PII_REVIEW and surface the findings so the user can confirm they
    # are comfortable proceeding (or cancel and delete the upload). Once the
    # user proceeds, the confirm lambda re-enqueues the job with
    # pii_acknowledged=true and we skip the scan on the second pass.
    if not job_record.get("pii_acknowledged"):
        transcript_text = "\n".join(
            u.get("text", "")
            for doc in parsed_docs
            for u in doc.get("utterances", [])
        )
        findings = scan_for_direct_identifiers(
            transcript_text, BEDROCK_GUARDRAIL_ID, BEDROCK_GUARDRAIL_VERSION
        )
        if findings:
            summary = ", ".join(f"{f['type']}={f['count']}" for f in findings)
            print(f"Job {job_id} PII_REVIEW: direct identifiers found ({summary})")
            update_job_status(
                job_id, "PII_REVIEW",
                error_message="Possible personal identifiers were found in the "
                              "transcript. Review them and choose whether to proceed.",
                pii_findings=findings,
            )
            os.remove(local_path)
            return

    annotations = await annotate_with_multi_pass_claude(
        parsed_docs=parsed_docs,
        num_passes=NUM_PASSES,
        scope="doc",
        selected_doc_id=parsed_docs[0]["doc_id"],
        interview_age=interview_age,
    )

    results_key = f"results/{job_id}/annotations.json"
    s3.put_object(
        Bucket=RESULTS_BUCKET,
        Key=results_key,
        Body=json.dumps(annotations, indent=2, default=str),
        ContentType="application/json",
    )

    # The interview_id is the uploaded filename without its extension -- this is
    # what the predictions table and the review key are keyed on.
    interview_id = os.path.splitext(os.path.basename(filename))[0]
    write_prediction_rows(job_id, category, interview_id, annotations, interview_age, hero_id)

    update_job_status(job_id, "COMPLETED", results_key=results_key)
    os.remove(local_path)


def extract_job_info(message_body):
    body = json.loads(message_body)
    for record in body.get("Records", [body]):
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", "")
        key = urllib.parse.unquote_plus(s3_info.get("object", {}).get("key", ""))
        if key.startswith("uploads/"):
            parts = key.split("/")
            job_id = parts[1]
            filename = "/".join(parts[2:])
            return job_id, key, filename
    return None, None, None


def poll_queue():
    print(f"Worker started, polling {QUEUE_URL}")
    while True:
        resp = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
        )

        messages = resp.get("Messages", [])
        if not messages:
            continue

        for msg in messages:
            job_id, s3_key, filename = extract_job_info(msg["Body"])
            if not job_id:
                print(f"Could not parse message: {msg['Body'][:200]}")
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                continue

            print(f"Processing job {job_id}: {filename}")
            try:
                asyncio.run(process_job(job_id, s3_key, filename))
                print(f"Job {job_id} completed")
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                print(f"Job {job_id} failed: {error_msg}")
                traceback.print_exc()
                update_job_status(job_id, "FAILED", error_message=error_msg[:500])

            sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])


if __name__ == "__main__":
    poll_queue()
