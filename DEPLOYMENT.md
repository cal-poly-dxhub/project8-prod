# Deployment

This deploys the P8 Annotation Pipeline into an AWS account with CDK. See
`ARCHITECTURE.md` for what gets created.

## Prerequisites
- An AWS account with credentials configured, so that
  `aws sts get-caller-identity` works
- **Amazon Bedrock model access** enabled in the target region. The pipeline
  calls Anthropic Claude models through the Converse API.
- Node.js 18 or later, plus npm
- Python 3.11 or later
- Docker, **running**, since CDK builds the Fargate worker image locally. Start
  Docker Desktop (or your daemon) before deploying or bootstrap/deploy will fail.
- The AWS CDK v2 CLI, **version 2.1129.0 or later**. The app pins a recent
  `aws-cdk-lib`, whose cloud-assembly schema an older CLI cannot read (you would
  see a "Cloud assembly schema version mismatch" error). Install a matching CLI
  with `npm i -g aws-cdk@latest`, or run every `cdk` command below through
  `npx -y aws-cdk@2.1129.0 ...` without a global install.

## 1. Install dependencies
```bash
pip install -r requirements.txt          # CDK app deps
cd frontend && npm install && cd ..       # frontend deps
```

## 2. Bootstrap CDK (once per account and region)
```bash
cdk bootstrap aws://<ACCOUNT_ID>/<REGION>
```
If bootstrap fails complaining that an existing `cdk-hnb659fds-*` role needs a
`Retain` deletion policy, the account has leftover state from an earlier
half-finished bootstrap. Delete the stuck `CDKToolkit` stack and the orphaned
role, then re-run:
```bash
aws cloudformation delete-stack --stack-name CDKToolkit --region <REGION>
aws iam delete-role --role-name cdk-hnb659fds-cfn-exec-role-<ACCOUNT_ID>-<REGION>
```

## 3. Deploy the stack
The account and region resolve from CDK context first, then env vars, then your
CLI credentials, with a default region of `us-west-2`. The simplest form:
```bash
cdk deploy P8IntegratedStack -c account=<ACCOUNT_ID> -c region=<REGION>
```
When it succeeds, note the stack **outputs**: `CloudFrontURLOutput`,
`ApiURLOutput`, `UserPoolIdOutput`, `UserPoolClientIdOutput`, and
`FrontendBucketOutput`.

## 4. Configure and build the frontend
```bash
cd frontend
cp .env.example .env
# fill these in from the stack outputs:
#   VITE_USER_POOL_ID=<UserPoolIdOutput>
#   VITE_USER_POOL_CLIENT_ID=<UserPoolClientIdOutput>
#   VITE_API_URL=<ApiURLOutput>
npm run build
```

## 5. Publish the frontend
Sync the build to the frontend bucket (`FrontendBucketOutput` from the stack),
then invalidate CloudFront. Get the distribution id from the CloudFront console
or CLI:
```bash
aws s3 sync dist/ s3://<FrontendBucketOutput> --delete
aws cloudfront create-invalidation --distribution-id <DIST_ID> --paths "/*"
```

## 6. Create a reviewer login
Self-signup is turned off, so create a user directly in the Cognito user pool:
```bash
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolIdOutput> \
  --username reviewer@example.com \
  --temporary-password '<TempPass123!>'
```

Open the CloudFront URL and sign in.

## 7. (Optional) Migrate existing review data
A fresh deploy comes up with empty tables. If you are carrying over predictions
and reviews from a previous deployment, use `scripts/migrate_legacy_data.py`.
The interview transcripts and reviews are **not** in this repo (they are not
public data); they are delivered separately as a snapshot directory containing
`interview_results/*.json` and `reviews.json`.

The migration is additive and reads only from the snapshot copy -- it never
touches any source system. Always dry-run first to confirm every review attaches
to a prediction before writing anything:
```bash
# validate offline, write nothing, no AWS calls:
python scripts/migrate_legacy_data.py --snapshot <SNAPSHOT_DIR> --dry-run

# then write into the deployed tables (names from the stack outputs):
export AWS_DEFAULT_REGION=<REGION>
python scripts/migrate_legacy_data.py \
  --snapshot <SNAPSHOT_DIR> \
  --category P8 \
  --table <PredictionsTableOutput> \
  --categories-table <CategoriesTableOutput>
```
Pass `--categories-table` so the category is registered and appears in the UI
selector. Without it the predictions are written but stay invisible in the app,
because the category dropdown lists only what exists in the categories table.
The dry-run prints a summary (rows, status counts, and any `unmatched_reviews`).
If `unmatched_reviews` or `unparseable_review_keys` is nonzero it exits without
writing -- fix the snapshot before running the real migration.

## Notes
- The Fargate service runs at `desired_count=0` and only scales up when jobs are
  queued, so it costs nothing while idle.
- The buckets, DynamoDB tables, and Cognito pool are set to **RETAIN** on stack
  deletion. If you are tearing the system down for good, delete them by hand.
