import boto3
import asyncio
import os
import json
from datetime import datetime
from pathlib import Path
from botocore.config import Config
from botocore.exceptions import ClientError
from config import BEDROCK_MODEL_ID, BEDROCK_REGION, ENABLE_EXTENDED_THINKING, MAX_READ_TIMEOUT, THINKING_BUDGET_TOKENS, TEMPERATURE, BEDROCK_GUARDRAIL_ID, BEDROCK_GUARDRAIL_VERSION


_reasoning_log_dir = Path("/tmp/reasoning_traces")


def _guardrail_config():
    # Returns the converse guardrailConfig when a guardrail is configured via
    # env (Fargate worker), else None so local runs skip it entirely.
    if BEDROCK_GUARDRAIL_ID:
        return {
            "guardrailIdentifier": BEDROCK_GUARDRAIL_ID,
            "guardrailVersion": BEDROCK_GUARDRAIL_VERSION or "DRAFT",
            # Detect mode: we want detections in the trace, not blocking.
            "trace": "enabled",
        }
    return None


def _log_guardrail_trace(response):
    # In detect mode the guardrail blocks nothing; it only reports what PII/PHI
    # it found in the trace. Surface a per-entity count in the worker logs so
    # operators can see when transcripts contain PHI.
    trace = response.get("trace", {}).get("guardrail", {})
    counts = {}
    for assessment in trace.get("inputAssessment", {}).values():
        for pii in assessment.get("sensitiveInformationPolicy", {}).get("piiEntities", []):
            counts[pii.get("type", "UNKNOWN")] = counts.get(pii.get("type", "UNKNOWN"), 0) + 1
    if counts:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"  Guardrail PHI detected (flagged, not blocked): {summary}")


def _log_reasoning_trace(group_name, thinking_text, annotation_count):
    _reasoning_log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = _reasoning_log_dir / f"{group_name}_{timestamp}.txt"
    with open(log_file, "w") as f:
        f.write(f"Group: {group_name}\n")
        f.write(f"Model: {BEDROCK_MODEL_ID}\n")
        f.write(f"Annotations returned: {annotation_count}\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write("=" * 80 + "\n\n")
        f.write(thinking_text)
    print(f"   Reasoning trace saved: {log_file.name}")


def _create_bedrock_client():
    import base64

    bearer_token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    if bearer_token:
        token = bearer_token[4:] if bearer_token.startswith('ABSK') else bearer_token
        decoded = base64.b64decode(token).decode('utf-8')
        access_key, secret_key = decoded.split(':', 1)

        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=BEDROCK_REGION
        )
        return session.client(
            "bedrock-runtime",
            region_name=BEDROCK_REGION,
            config=Config(
                read_timeout=MAX_READ_TIMEOUT,
                retries={'max_attempts': 3}
            )
        )

    return boto3.client(
        "bedrock-runtime",
        region_name=BEDROCK_REGION,
        config=Config(
            read_timeout=MAX_READ_TIMEOUT,
            retries={'max_attempts': 3}
        )
    )


bedrock = _create_bedrock_client()


def blocking_bedrock_call_for_group(prompt, transcript, group_name):
    try:
        annotations, thinking_text = blocking_bedrock_call_structured(prompt, transcript)

        if thinking_text:
            _log_reasoning_trace(group_name, thinking_text, len(annotations))

        for annotation in annotations:
            annotation["source"] = f"claude_{group_name}"
            annotation["group"] = group_name

        return annotations

    except Exception as e:
        print(f"Error for group {group_name}: {str(e)}")
        return []


def blocking_bedrock_call(prompt, transcripts):
    kwargs = dict(
        modelId=BEDROCK_MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {"text": prompt},
                    {"cachePoint": {"type": "default"}},
                    {"text": transcripts}
                ]
            }
        ],
        inferenceConfig={
            "temperature": TEMPERATURE,
            "maxTokens": 65536
        }
    )
    guardrail = _guardrail_config()
    if guardrail:
        kwargs["guardrailConfig"] = guardrail
    response = bedrock.converse_stream(**kwargs)
    chunks = []
    for event in response["stream"]:
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"]["delta"]
            text = delta.get("text")
            if text:
                chunks.append(text)
    return "".join(chunks)


def blocking_bedrock_call_structured(prompt, transcripts):
    try:
        tools = [{
            "toolSpec": {
                "name": "medical_annotation",
                "description": "Extract medical concept annotations from text",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "paragraph_id": {"type": "string"},
                                        "sentence_indices": {"type": "array", "items": {"type": "integer"}},
                                        "mentioned_verbatim": {"type": "boolean"},
                                        "concept_id": {"type": "integer"},
                                        "concept_name": {"type": "string"},
                                        "age": {"type": "string"},
                                        "caused_by": {"type": "array", "items": {"type": "integer"}},
                                        "rationale": {"type": "string"},
                                        "source": {"type": "string"}
                                    },
                                    "required": ["paragraph_id", "sentence_indices", "concept_id", "concept_name", "mentioned_verbatim"]
                                }
                            }
                        },
                        "required": ["items"]
                    }
                }
            }
        }]
        messages = [
            {
                "role": "user",
                "content": [
                    {"text": prompt},
                    {"cachePoint": {"type": "default"}},
                    {"text": f"Text to analyze:\n{transcripts}"}
                ]
            }
        ]
        additional_fields = {}
        if ENABLE_EXTENDED_THINKING:
            additional_fields = {
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": THINKING_BUDGET_TOKENS
                }
            }

        converse_kwargs = dict(
            modelId=BEDROCK_MODEL_ID,
            messages=messages,
            toolConfig={"tools": tools},
            inferenceConfig={
                "maxTokens": 65536,
                "temperature": TEMPERATURE
            },
            additionalModelRequestFields=additional_fields
        )
        guardrail = _guardrail_config()
        if guardrail:
            converse_kwargs["guardrailConfig"] = guardrail
        response = bedrock.converse(**converse_kwargs)
        if guardrail:
            _log_guardrail_trace(response)
        thinking_text = ""
        if 'output' in response and 'message' in response['output']:
            content = response['output']['message'].get('content', [])
            for item in content:
                if 'reasoningContent' in item:
                    reasoning = item['reasoningContent'].get('reasoningText', {})
                    thinking_text += reasoning.get('text', '')
                if 'toolUse' in item:
                    tool_input = item['toolUse'].get('input', {})
                    if 'items' in tool_input:
                        print(f"  Structured output: Found {len(tool_input['items'])} annotations")
                        return tool_input['items'], thinking_text
            print("  No tool use found in response")
            return [], thinking_text
        else:
            print("  No message content in response")
            return [], thinking_text
    except Exception as e:
        print(f"  Structured output error: {str(e)}")
        return [], ""


async def query_claude_with_bedrock(prompt, transcripts, idx, semaphore, progress_bar, total_batches, completed_ref, lock):
    async with semaphore:
        try:
            print("Processing batch", idx)
            result = await asyncio.to_thread(blocking_bedrock_call, prompt, transcripts)
            async with lock:
                completed_ref[0] += 1
            return idx, result
        except (ClientError, Exception) as e:
            print(f"ERROR: Can't invoke '{BEDROCK_MODEL_ID}'. Reason: {e}")
            return idx, None
