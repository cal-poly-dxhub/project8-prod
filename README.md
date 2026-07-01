# P8 Annotation Pipeline

An AWS system that annotates patient and caregiver interview transcripts against
a disease-concept codebook using Amazon Bedrock. It comes with a web app where
reviewers validate the AI's predictions and explore the results.

- **`ARCHITECTURE.md`** covers the system design, the components, and the data model.
- **`DEPLOYMENT.md`** covers how to deploy it into an AWS account with CDK.
- **`p8-annotation-pipeline.drawio.png`** is the architecture diagram.

## What it does
1. A reviewer uploads a `.docx` interview and tags it with a disease or mutation
   **category**.
2. An ECS Fargate worker runs a three-stage Bedrock annotation pipeline and
   writes one prediction row per annotation into DynamoDB.
3. Reviewers approve or reject those predictions and view aggregate charts. All
   of this reads from a single predictions table.

## Tech
CDK (Python), Lambda, API Gateway, Cognito, S3, SQS, ECS Fargate, DynamoDB,
Amazon Bedrock with a PHI guardrail, CloudFront, and a React + Tailwind frontend
built with Vite.

## Quick start
Full steps are in **`DEPLOYMENT.md`**. The short version:
```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
cdk bootstrap aws://<ACCOUNT_ID>/<REGION>
cdk deploy P8IntegratedStack -c account=<ACCOUNT_ID> -c region=<REGION>
```

## Status
This is a working prototype and still under active development. It has not been
hardened for production. See `DISCLAIMER_original.md` for the full disclaimer.
