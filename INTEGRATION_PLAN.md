# P8 Integrated System — Implementation Plan

Target: full integration deployed to 8p's AWS account by **July 6 2026**.

## Goal

Turn three disconnected single-disease tools into one category-driven system:

1. Upload docx + choose/create a **category** -> interview belongs to that category
2. Pipeline predicts concepts (standard 543-concept codebook, unchanged)
3. Predictions visible in the site AND reviewable, both filtered by category
4. Review: pick category -> approve/reject -> at 2 approvals the prediction
   flips to APPROVED in real time
5. Visualizations by category (concept distribution, age)
6. Later: more diseases/mutations = just more category labels (no codebook change)

Category = a label on the interview. Same standard codebook for every category.

## Deployment strategy: FRESH PARALLEL STACK (safety)

Do NOT modify the deployed `P8AnnotationStack` or the EC2 dashboard. Build the
integrated system as a NEW, independent stack (`P8IntegratedStack`) deployed
ALONGSIDE the old one in <DEV_ACCOUNT_ID> for dev/test. The old stack + EC2 box
stay running as fallback and are decommissioned only after cutover, on the
user's explicit go-ahead.

Rationale: nothing precious lives only in the old stack (codebook in git +
dxhub-project-8-heros; old preds in p8-ec2-latest snapshot; 1,560 reviews in
s3://p8-review-dashboard-backups). The old deployed stack holds just 2 throwaway
jobs + 3 result files. A fresh stack risks nothing and isn't constrained by old
resource shapes.

GOTCHA: current stack hardcodes physical names (table_name "p8-annotation-jobs",
user_pool_name "p8-annotation-users", guardrail "p8-phi-detection", api
"P8 Annotation API"). A parallel stack in the SAME account MUST use different
names (prefix or CloudFormation auto-naming) or deploy fails on collision.

Safety rules (binding):
- Additive/parallel only. Never rename/retype/delete existing live resources.
- Never run cdk destroy / cdk deploy without showing cdk diff + getting OK.
- Never run aws delete-* against live resources.
- Migrations read from COPIES (S3 backups, snapshots), write to NEW tables;
  never mutate source data or live reviews.json or the running EC2 box.
- Validate locally with cdk synth (no AWS calls) while building.

## Core architectural decision

A single **predictions table** (DynamoDB) is the source of truth. Each
annotation becomes one row, tagged with category and a review status. The site
results view, the review view, and the visualizations are all just different
queries over this one table. This is what unifies the three tools.

### Predictions table schema

```
PK:  category            (e.g. "P8")
SK:  interview_id#idx     (e.g. "Caregiver 11#49")  -- stable, order-derived
attrs:
  concept_id, concept_name, quote (raw_highlight), age, rationale,
  caused_by, paragraph_id, source_job_id,
  status            PENDING | APPROVED | REJECTED
  approvals         [reviewer_id, ...]
  rejections        [{reviewer_id, reasons[], comment}, ...]
  review_count      int
GSI: category + status   (for "pending in category X", "approved in category X")
```

The 2-approval rule: on each vote, recompute. `len(approvals) >= 2` -> APPROVED.
Majority logic ported from the existing dashboard's `grouping.js`.

## Component changes

### A. Upload flow (category)
- `categories` table (or a config item): list of category names.
- Upload form: dropdown of existing categories + "create new" text field.
- `presigned_url` lambda: accept `category`, store on job record, put it in the
  S3 key: `uploads/{category}/{job_id}/{filename}`.
- Job record gains `category`.

### B. Worker (predictions as rows)
- After producing annotations, write each one as a row in the predictions table
  with the job's category and `status=PENDING`.
- Keep the S3 annotations.json (useful as raw artifact / download).
- SK index must match the migration's ordering convention (interview_id#idx).

### C. Review view (in the web app, replaces EC2 dashboard)
- New route in the React app: category filter -> pending predictions list.
- Approve / reject (with rejection reasons, ported list) -> calls a new
  `vote` lambda that updates approvals/rejections + recomputes status.
- Reviewer identity = Cognito sub. One vote per reviewer per prediction.
- Live update: re-query after vote (polling is fine for this scale).

### D. Visualizations (by category)
- Host the Observable Framework app behind CloudFront (new behavior or a
  second distribution).
- Feed it from an aggregate endpoint (approved predictions grouped by
  concept / age) filtered by category, instead of a static export.

### E. Data migration (run on July 6 into 8p's account)
Confirmed feasible. Scripts:
1. **Codebook + notes** -> load `codebook_with_notes.csv` into the worker image
   / reference store (already in the image; just confirm).
2. **Old predictions** -> read `interview_results/*.json` (12 interviews,
   order preserved), write rows tagged `category="P8"`, SK = `interview#idx`
   using the SAME idx the dashboard used (enumerate claude_raw_output).
3. **Reviews** -> read live `reviews.json` (1,560 keys like "Caregiver 11_49"),
   split into interview_id + idx, attach each reviewer's decision to the
   matching prediction row, recompute status via the 2-approval rule.

CRITICAL: the review key `interviewId_idx` is POSITIONAL (idx into the
interview's claude_raw_output). Migration MUST enumerate predictions in the
exact original order or reviews attach to the wrong concepts. Verified:
`Caregiver 11_49` -> idx 49 in Caregiver_11.json -> concept 200 Hypotonia.

## Build sequence (dependency order)

1. Predictions table + categories store (CDK) — foundation for everything
2. Upload category (frontend + presigned_url lambda + job record)
3. Worker writes prediction rows
4. Migration scripts (old preds + reviews) — can build/test in parallel with 3
5. Review view + vote lambda (the 2-approval rule)
6. Visualizations hosting + aggregate endpoint, category-filtered
7. End-to-end test in <DEV_ACCOUNT_ID>, then deploy + migrate into 8p account

## Risks / honest notes
- 9 days for full integration is aggressive. Highest-value, lowest-risk slice
  if time slips: A+B+E (category uploads + predictions table + migrated data),
  then C (review) then D (viz).
- Decommissioning the EC2 dashboard means reviewers switch to the in-app
  review view; needs a heads-up to the 9 reviewers.
- Real-time = poll-after-vote (no websockets needed at this scale).
```
