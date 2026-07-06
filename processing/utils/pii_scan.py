"""Upload-time PII gate.

We scan the interview transcript for DIRECT identifiers once, up front, using
the Bedrock ApplyGuardrail API (decoupled from any model invocation). If the
transcript carries direct identifiers the job is rejected and the user is asked
to re-upload a redacted copy -- the text never reaches the annotation model,
the results bucket, or the predictions table.

AGE is deliberately NOT treated as a direct identifier here: it is present in
essentially every transcript and is clinically meaningful to the disease
concept model, so rejecting on age would reject every upload. The guardrail
still reports age (and we ignore it); we only reject on the identifiers below.
"""
import os
import boto3

# Direct identifiers that must not enter the pipeline. Mirrors the guardrail's
# PII entity types MINUS AGE (see module docstring).
DIRECT_IDENTIFIERS = {
    "NAME", "EMAIL", "PHONE", "ADDRESS", "USERNAME",
    "US_SOCIAL_SECURITY_NUMBER", "US_PASSPORT_NUMBER", "DRIVER_ID",
    "CA_HEALTH_NUMBER", "UK_NATIONAL_HEALTH_SERVICE_NUMBER",
}

# ApplyGuardrail accepts up to 25 text units of 1,000 chars each per request.
# Stay comfortably under that so a single call never trips the size limit.
_MAX_CHARS_PER_CALL = 24_000

_region = os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION", "us-west-2")
_bedrock_runtime = boto3.client("bedrock-runtime", region_name=_region)


def _chunks(text):
    for start in range(0, len(text), _MAX_CHARS_PER_CALL):
        yield text[start:start + _MAX_CHARS_PER_CALL]


def _mask(match_text):
    # Never echo full PII back to the user. Keep only the first character so a
    # reviewer can locate it in their document without us surfacing the value.
    if not match_text:
        return ""
    head = match_text.strip()[:1]
    return f"{head}…" if head else ""


def scan_for_direct_identifiers(text, guardrail_id, guardrail_version):
    """Return a list of {type, count, sample} for direct identifiers found.

    Returns [] when the guardrail is not configured (e.g. local runs) or when
    no direct identifiers are present. AGE and any other non-direct entity are
    ignored.
    """
    if not (guardrail_id and text):
        return []

    findings = {}  # type -> {count, sample}
    for chunk in _chunks(text):
        resp = _bedrock_runtime.apply_guardrail(
            guardrailIdentifier=guardrail_id,
            guardrailVersion=guardrail_version or "DRAFT",
            source="INPUT",
            # FULL is required: the guardrail's PII action is NONE (it never
            # intervenes), so with the default INTERVENTIONS scope detected-
            # but-not-blocked entities would be omitted from the response.
            outputScope="FULL",
            content=[{"text": {"text": chunk}}],
        )
        for assessment in resp.get("assessments", []):
            pii = assessment.get("sensitiveInformationPolicy", {}).get("piiEntities", [])
            for entity in pii:
                etype = entity.get("type", "")
                if etype not in DIRECT_IDENTIFIERS or not entity.get("detected", True):
                    continue
                slot = findings.setdefault(etype, {"count": 0, "sample": ""})
                slot["count"] += 1
                if not slot["sample"]:
                    slot["sample"] = _mask(entity.get("match", ""))

    return [
        {"type": etype, "count": slot["count"], "sample": slot["sample"]}
        for etype, slot in sorted(findings.items())
    ]
