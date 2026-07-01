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

# Disclaimers 

Customers are responsible for making their own independent assessment of the information in this document. 

This document: 

(a) is for informational purposes only, 

(b) references AWS product offerings and practices, which are subject to change without notice, 

(c) does not create any commitments or assurances from AWS and its affiliates, suppliers or licensors. AWS products or services are provided "as is" without warranties, representations, or conditions of any kind, whether express or implied. The responsibilities and liabilities of AWS to its customers are controlled by AWS agreements, and this document is not part of, nor does it modify, any agreement between AWS and its customers, and 

(d) is not to be considered a recommendation or viewpoint of AWS. 

Additionally, you are solely responsible for testing, security and optimizing all code and assets on GitHub repo, and all such code and assets should be considered: 

(a) as-is and without warranties or representations of any kind, 

(b) not suitable for production environments, or on production or other critical data, and 

(c) to include shortcuts in order to support rapid prototyping such as, but not limited to, relaxed authentication and authorization and a lack of strict adherence to security best practices. 

All work produced is open source. More information can be found in the GitHub repo.
