# P8 Annotation Pipeline: Architecture

This system ingests patient and caregiver interview transcripts, uses Amazon
Bedrock to annotate them against a disease-concept codebook, and gives human
reviewers a web app to validate the AI's predictions and explore the results.

Everything is defined as infrastructure-as-code with AWS CDK in Python, and it
deploys into any AWS account with one `cdk deploy`.

---

## How it flows

```
                        ┌─────────────────────────────────────────────┐
                        │                CloudFront                    │
                        │        (serves the React SPA over HTTPS)     │
                        └───────────────────────┬─────────────────────┘
                                                │
             ┌──────────────────────────────────┼──────────────────────────────┐
             │                                  │                               │
      ┌──────▼──────┐                    ┌──────▼───────┐                ┌───────▼───────┐
      │  Frontend   │  Cognito-authed    │  API Gateway │   invokes      │   Lambdas     │
      │  S3 bucket  │  REST calls  ─────▶│  (REST API)  │ ─────────────▶ │ (9 handlers)  │
      └─────────────┘                    └──────────────┘                └───────┬───────┘
                                                                                 │
                       ┌─────────────────────────────────────────────────────────┤
                       │                        reads/writes                      │
              ┌────────▼─────────┐   ┌──────────────────┐   ┌─────────────────────▼──────┐
              │  Uploads bucket  │   │   Results bucket │   │        DynamoDB            │
              │  (raw .docx)     │   │   (result JSON)  │   │  jobs / categories /       │
              └────────┬─────────┘   └──────────────────┘   │  predictions (the spine)   │
                       │ S3 event                            └────────────────────────────┘
                       ▼                                                  ▲
                 ┌──────────┐        pull job        ┌─────────────────┐  │ writes prediction rows
                 │   SQS    │ ─────────────────────▶ │  ECS Fargate    │──┘
                 │  queue   │                        │  worker (Docker)│
                 └──────────┘                        └────────┬────────┘
                       ▲ scales 0..5                          │ Converse + Guardrail
                       │ on queue depth              ┌────────▼────────┐
                       └─────────────────────────────│ Amazon Bedrock  │
                                                     │ (+ PHI Guardrail)│
                                                     └─────────────────┘
```

1. A reviewer signs in through Cognito and uploads a `.docx` interview tagged
   with a **category**, which is a disease or mutation cohort.
2. The upload lands in the **uploads S3 bucket** through a presigned URL. The
   `PUT` fires an S3 event to **SQS**.
3. An **ECS Fargate worker**, scaled up from the queue, pulls the job and runs
   the three-stage Bedrock annotation pipeline. It writes the full result JSON
   to the **results bucket** and writes one **prediction row per annotation**
   into the DynamoDB predictions table, tagged with the category and set to
   `PENDING`.
4. Reviewers use the web app to approve or reject predictions, with blind review
   and a majority tie-break, and to view the aggregate charts. Both features are
   queries against that one predictions table.

---

## The data spine: one predictions table

The design centers on a single DynamoDB **predictions table**. Every annotation
the pipeline produces becomes one row, and the upload, review, and
visualization features all read from it.

- **Partition key:** `category`
- **Sort key:** `prediction_id`, formatted as `"{interview_id}#{idx}"`, where
  `idx` is the annotation's position in the interview's prediction list. The
  order is preserved.
- Each row holds the concept id and name, the verbatim quote, the age, the
  rationale, a review `status` (`PENDING`, `APPROVED`, `REJECTED`, or
  `CONFLICT`), and the reviewer vote lists (approvals and rejections with
  reasons).
- The **`category-status-index` GSI** answers the question "which pending or
  approved predictions exist in category X" for the review queue and the charts.

This is why upload tags a category, the worker writes rows, and review and
visualization sit on top as thin query layers. The table is the contract
between all three.

Two supporting tables back it up:
- **jobs** holds one row per uploaded interview, with status, filenames, and
  timestamps. It has a `category-index` GSI.
- **categories** holds one item per category name, populated by the "choose
  existing or create new" control on upload.

---

## Components

### Frontend (`frontend/`)
React, TypeScript, and Vite, styled with **Tailwind CSS v4**. It builds to
static assets that live in a private S3 bucket and are served through
CloudFront, with an SPA fallback that rewrites 403 and 404 responses to
`index.html`.

Auth runs through AWS Amplify against the Cognito user pool, and every API call
carries the Cognito JWT. The app has three tabs: **Pipeline** for upload, job
list, and results; **Review** for per-interview approve and reject; and
**Visualizations** for the five charts built with Observable Plot and d3 over
the `/aggregate` endpoint.

### API (`lambdas/`)
Nine Python 3.11 Lambda handlers sit behind an API Gateway REST API. A Cognito
authorizer protects every route.

| Route | Method | Handler | Purpose |
|-------|--------|---------|---------|
| `/uploads` | POST | `presigned_url` | Create a job and a presigned S3 upload URL |
| `/categories` | GET/POST | `categories` | List or create categories |
| `/jobs` | GET | `list_jobs` | List the caller's jobs |
| `/jobs/{id}/status` | GET | `job_status` | Poll a job's status |
| `/jobs/{id}/results` | GET | `get_results` | Presigned URL for the result JSON |
| `/predictions` | GET | `list_predictions` | Predictions for an interview |
| `/predictions/{id}/vote` | POST | `vote` | Approve or reject a prediction |
| `/interviews` | GET | `list_interviews` | Per-interview review summaries |
| `/aggregate` | GET | `aggregate` | Concept frequencies and quotes for the charts |

### Processing worker (`processing/`)
A Docker container that runs on **ECS Fargate** with 1 vCPU and 2 GB of memory.
SQS queue depth scales it between **0 and 5 tasks**. It sits at `desired_count=0`
when idle, so there is no compute cost while no jobs are queued.

The worker runs the **three-stage annotation pipeline** against Amazon Bedrock.
It bundles its own copy of the config, prompts, codebook, and utils, so the
container is self-contained. When it finishes, it writes the result JSON to the
results bucket and the prediction rows to DynamoDB.

### Bedrock and the PHI guardrail
Annotation runs through Bedrock's Converse API. A **Bedrock guardrail** is
attached in detect mode, with every entity set to `action=NONE`. It flags PII
and PHI entities in the transcripts (name, email, phone, address, age, SSN,
health numbers, and similar) but does not block them, so nothing is silently
dropped from a transcript.

---

## Deploying into any account

The stack deploys into a fresh account with no code edits:

- **No hardcoded physical names.** Resources use CloudFormation auto-generated
  names, so the stack can even run next to the legacy `P8AnnotationStack` in the
  same account without a collision.
- **Account and region resolution** in `app.py` falls back in this order:
  1. CDK context: `cdk deploy -c account=<id> -c region=<region>`
  2. `CDK_DEPLOY_ACCOUNT` and `CDK_DEPLOY_REGION`
  3. `CDK_DEFAULT_ACCOUNT` and `CDK_DEFAULT_REGION`, which come from the CLI's
     current credentials
  4. a region default of `us-west-2`, chosen for Bedrock model availability
- **Retention.** The buckets, tables, and user pool are set to `RETAIN` on stack
  delete. The frontend bucket is set to `DESTROY` with auto-delete.
- **Outputs** expose the CloudFront URL, the API URL, the Cognito pool and
  client ids, and the table and bucket names, which is what you need to wire up
  the frontend `.env`.

`DEPLOYMENT.md` has the step-by-step deploy.

---

## Repository layout

```
app.py                     CDK app entry (account/region resolution, 2 stacks)
cdk.json                   CDK config
requirements.txt           CDK Python deps
stacks/
  integrated_stack.py      The stack that defines the system above
  main_stack.py            Legacy stack, kept for reference and coexistence
lambdas/<name>/handler.py  API handlers, one folder each
processing/                Fargate worker (Dockerfile, worker.py, prompts, utils)
frontend/                  React + Tailwind SPA (Vite)
scripts/migrate_legacy_data.py   One-off legacy-data migration
INTEGRATION_PLAN.md        Design notes for the category-driven integration
p8-annotation-pipeline.*   Architecture diagram (drawio, png, md)
```
