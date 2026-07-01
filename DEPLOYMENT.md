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
- Docker, since CDK builds the Fargate worker image locally
- The AWS CDK v2 CLI (`npm i -g aws-cdk`)

## 1. Install dependencies
```bash
pip install -r requirements.txt          # CDK app deps
cd frontend && npm install && cd ..       # frontend deps
```

## 2. Bootstrap CDK (once per account and region)
```bash
cdk bootstrap aws://<ACCOUNT_ID>/<REGION>
```

## 3. Deploy the stack
The account and region resolve from CDK context first, then env vars, then your
CLI credentials, with a default region of `us-west-2`. The simplest form:
```bash
cdk deploy P8IntegratedStack -c account=<ACCOUNT_ID> -c region=<REGION>
```
When it succeeds, note the stack **outputs**: `CloudFrontURLOutput`,
`ApiURLOutput`, `UserPoolIdOutput`, and `UserPoolClientIdOutput`.

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
Sync the build to the frontend bucket, then invalidate CloudFront. Get the
bucket name from the stack (it is the CloudFront origin) and the distribution id
from the CloudFront console or CLI:
```bash
aws s3 sync dist/ s3://<FRONTEND_BUCKET> --delete
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

## Notes
- The Fargate service runs at `desired_count=0` and only scales up when jobs are
  queued, so it costs nothing while idle.
- The buckets, DynamoDB tables, and Cognito pool are set to **RETAIN** on stack
  deletion. If you are tearing the system down for good, delete them by hand.
