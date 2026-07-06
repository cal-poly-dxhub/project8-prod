# LLM / Agent Guide to This Codebase

This file orients an AI coding assistant (or a new engineer) working on the P8
Annotation Pipeline. Read `ARCHITECTURE.md` for the system design and
`DEPLOYMENT.md` for the deploy runbook. This document focuses on **how the code
is wired, where things live, and the non-obvious traps** that are easy to break.

---

## What this system is (one paragraph)

Reviewers upload `.docx` interview transcripts tagged with a **category** (a
disease/mutation cohort). An ECS Fargate worker runs a multi-pass Amazon Bedrock
(Claude) annotation pipeline against a disease-concept codebook, writing one
**prediction row per annotation** into a single DynamoDB table. A React SPA lets
users review predictions (approve/reject, blind review with majority tie-break)
and view aggregate charts. Everything is AWS CDK (Python), deployable into any
account with one `cdk deploy`.

---

## Repository map

```
app.py                        CDK app entry. Resolves account/region, defines 2 stacks.
cdk.json                      CDK config (points at app.py).
requirements.txt              CDK Python deps.
stacks/
  integrated_stack.py         THE stack. Everything below is defined here. Start here.
  main_stack.py               Legacy stack, kept only for coexistence/reference. Do not extend.
lambdas/<name>/handler.py     One folder per API handler. Entry is always handler.handler.
processing/
  worker.py                   Fargate worker loop: SQS -> parse -> PII scan -> annotate -> write.
  Dockerfile                  Builds the worker image (CDK builds it locally at deploy).
  config.py                   NUM_PASSES and pipeline config.
  utils/                      parsers, annotation_engine, pii_scan (bundled into the image).
frontend/
  src/lib/api.ts              ALL API calls live here. One function per endpoint.
  src/components/             React components (JobList, Review, Visualizations, ui.tsx primitives).
  src/main.tsx                Amplify.configure from VITE_* env vars.
  .env.example                Template for the three VITE_ vars. Real .env is gitignored.
scripts/
  migrate_legacy_data.py      One-off legacy snapshot -> predictions table migration.
  backfill_interview_ages.py  One-off backfill of interview_age onto existing rows.
ARCHITECTURE.md               System design + data-flow diagram.
DEPLOYMENT.md                 Step-by-step deploy + user management + migration runbook.
```

---

## The data model (know this cold before touching anything)

Three DynamoDB tables, all `PAY_PER_REQUEST`, all `RETAIN` on delete.

### predictions table — THE SPINE
- `PK = category`, `SK = prediction_id` where `prediction_id = "{interview_id}#{idx}"`.
- `idx` is the annotation's **position** in the interview's prediction list. This
  positional key matches the legacy review-key convention (e.g. `Caregiver 11_49`)
  so migrated reviews attach to the right prediction. **Do not reorder annotations**
  between passes or you break this contract.
- `interview_id` = uploaded filename without extension.
- Row fields: `concept_id`, `concept_name`, `quote`, `age`, `rationale`,
  `caused_by`, `status` (PENDING/APPROVED/REJECTED/CONFLICT), `approvals`,
  `rejections`, `review_count`, `version`, optional `interview_age`.
- GSI `category-status-index` (`PK=category, SK=status`) powers the review queue
  and the charts.
- Upload, review, and visualization are all just queries over this one table.

### jobs table — one row per uploaded interview
- `PK = job_id`. Fields: `filename`, `status`, `user_id` (Cognito sub),
  `category`, `created_at`, `updated_at`, `error_message`, `pii_findings`,
  `pii_acknowledged`, optional `interview_age`.
- GSI `category-index` (`PK=category, SK=created_at`).
- GSI `user-index` (`PK=user_id, SK=created_at`) — **`list_jobs` depends on this.**
  See the trap below.

### categories table
- `PK = category`. One tiny item per category name. The upload "choose existing
  or create new" control reads/writes here. A category invisible in the UI
  dropdown almost always means it is missing from this table.

---

## Request lifecycles

### Upload -> annotation
1. `POST /uploads` (`lambdas/presigned_url`) creates a jobs row (status
   `UPLOADING`, stamps `user_id` from the Cognito claim, `category`, optional
   `interview_age`) and returns a presigned S3 PUT URL.
2. Frontend PUTs the `.docx` to the uploads bucket under `uploads/{job_id}/{filename}`.
3. The S3 `OBJECT_CREATED` event (prefix `uploads/`) fires to SQS.
4. `processing/worker.py` pulls the message, parses the key back into
   `job_id / s3_key / filename`, sets status `PROCESSING`.
5. **PII gate** (unless `pii_acknowledged`): scans the transcript for direct
   identifiers via `utils/pii_scan.py`. If any are found, it sets status
   `PII_REVIEW`, writes `pii_findings`, deletes the local temp file, and returns
   WITHOUT annotating.
6. Otherwise it runs `annotate_with_multi_pass_claude`, writes result JSON to the
   results bucket, writes prediction rows, sets status `COMPLETED`.

### PII decision
- `POST /jobs/{id}/pii-decision` (`lambdas/pii_decision`): "proceed" re-enqueues
  the job with `pii_acknowledged=true` (worker skips the scan on the second pass);
  "cancel" deletes the upload and marks the job `CANCELLED`.

### Review
- `GET /interviews` -> per-interview summaries. `GET /predictions?category=&interview=`
  -> the rows. `POST /predictions/{id}/vote` records an approve/reject. Review is
  **blind**: other reviewers' votes are redacted until the caller has voted.
  Status resolves by majority once enough votes land.

### Visualizations
- `GET /aggregate?category=` (`lambdas/aggregate`, 30s timeout) groups a
  category's predictions into concept frequencies, quotes, and per-interview sets,
  applying the "counts until rejected" rule. Feeds the five charts.

---

## The PII guardrail — the single most misconfigured thing

The Bedrock guardrail (`PHIGuardrail` in `integrated_stack.py`) is **detect-only**
and is NOT attached to any model call. The worker calls `ApplyGuardrail`
(source=INPUT) itself and reads the reported `piiEntities`.

Every entity is configured with `action=NONE` **AND** `input_action=NONE` +
`output_action=NONE`. This matters: `input_action` defaults to `BLOCK`, so if you
only set `action=NONE`, any transcript mentioning an AGE or NAME (i.e. every real
transcript) gets the whole request blocked (`stopReason=guardrail_intervened`),
silently zeroing out annotations. If annotations mysteriously come back empty
after a guardrail change, this is why. AGE is intentionally in the detected set
but a participant's age is treated as fine and is not surfaced as a blocker.

---

## Traps and gotchas (learned the hard way)

1. **Lambda-vs-CDK GSI drift.** `lambdas/list_jobs` queries the jobs table GSI
   `user-index`. If that index is not defined in `integrated_stack.py`, every
   `list_jobs` call throws `ValidationException` and returns nothing, so the UI
   shows "No jobs yet" forever even though rows exist (and PII findings / errors
   never render because the list itself is empty). If you add a query against a
   new index name in a lambda, you MUST add the matching `add_global_secondary_index`
   in the stack. After deploy, a new GSI can take several minutes to backfill to
   `ACTIVE` even on a 2-row table before queries return rows.

2. **Frontend `.env` corruption.** `VITE_*` vars are inlined at build time. If the
   `.env` contains stray bytes (e.g. ANSI escape codes from writing it via a shell
   heredoc that captured a syntax-highlighting pager's output), Vite silently
   parses garbage and builds a bundle with `undefined` config. Symptoms: "Auth
   UserPool not configured" on login, or API calls to `undefined/jobs`. Always
   write `.env` in an editor / with a file-writing tool, never a heredoc piping
   from `cat`/`bat`. Verify a build by grepping the pool id or API host out of
   `dist/assets/index-*.js`.

3. **DynamoDB rejects empty strings.** The worker strips `""` values before
   `put_item` (`{k: v for k, v in item.items() if v != ""}`). Preserve that when
   adding fields, or writes fail.

4. **Numbers come back as Decimal.** `interview_age` and similar are stored as
   numbers and returned as `Decimal`; coerce to `int` before using in prompts or
   JSON (`json.dumps(..., default=str)` is used where coercion is impractical).

5. **Annotation order is a contract.** `idx` positions predictions; migrated
   reviews attach by position. Do not sort/dedupe annotations in a way that shifts
   indices.

6. **CDK CLI version.** The app pins a recent `aws-cdk-lib`; an older CLI cannot
   read the cloud-assembly schema ("schema version mismatch"). Use
   `npx -y aws-cdk@2.1129.0` (or later) if the global CLI is old.

7. **Docker must be running** for deploy — CDK builds the Fargate worker image
   locally from `processing/Dockerfile`.

8. **`main_stack.py` is legacy.** New work goes in `integrated_stack.py`. The two
   coexist in one account because the integrated stack uses only auto-generated
   physical names (no hardcoded `table_name` / `user_pool_name`).

---

## How to make common changes

- **Add an API endpoint:** create `lambdas/<name>/handler.py` with a
  `handler(event, context)`; in `integrated_stack.py` add `make_fn(...)`, grant it
  the table/bucket access it needs, and wire the route under the right API Gateway
  resource with `**auth`. Add a matching function to `frontend/src/lib/api.ts`.
- **Add a jobs/predictions query by a new attribute:** add the GSI in the stack
  first (see trap #1), deploy, wait for `ACTIVE`, then query it in the lambda.
- **Change the annotation pipeline:** edit `processing/` (worker + utils). CDK
  rebuilds the image on next deploy. Keep prediction-row field shape and `idx`
  ordering stable.
- **Frontend change:** edit under `frontend/src`, `npm run build`, sync `dist/` to
  the frontend bucket, invalidate CloudFront. See DEPLOYMENT.md step 5-6.

---

## Auth and users

- Cognito, self-signup disabled (`AllowAdminCreateUserOnly`). Username = email.
- Password policy: 8+ chars, upper, lower, digit; **no symbol required**.
- The pool has no SES, so the automatic invite email is not delivered. Create
  users with `admin-create-user --message-action SUPPRESS` then
  `admin-set-user-password --permanent` and hand the user the password. Full
  commands in DEPLOYMENT.md step 6.
- Every API route is behind a Cognito authorizer; the frontend sends the JWT via
  Amplify. `user_id` on a jobs row is the token's `sub` claim.

---

## Deploy and migrate (pointers)

- Deploy: `DEPLOYMENT.md`. One `cdk deploy P8IntegratedStack -c account= -c region=`.
- Data migration: `scripts/migrate_legacy_data.py`, **always `--dry-run` first**;
  it aborts if any review cannot attach to a prediction. Pass `--categories-table`
  or the migrated category will not appear in the UI dropdown.
- Cost: Fargate sits at `desired_count=0` when idle, so there is no compute cost
  while no jobs are queued.
