# P8 Annotation Pipeline - AWS Architecture

## Overview

A serverless/containerized pipeline that processes medical interview transcripts (.docx files) through AI-powered annotation using Amazon Bedrock (Claude Sonnet 4.6). The system identifies disease concepts, impacts, and medical interventions from caregiver interviews.

## Architecture Components

| Service | Purpose |
|---------|---------|
| **CloudFront** | CDN serving the React frontend (SPA) |
| **S3 (Frontend)** | Hosts static website assets |
| **Cognito** | User authentication (email/password) |
| **API Gateway** | REST API with Cognito authorizer |
| **Lambda (x4)** | Presigned URL generation, job listing, status, results retrieval |
| **S3 (Uploads)** | Receives uploaded .docx interview files |
| **SQS** | Processing queue with Dead Letter Queue for failed messages |
| **ECS Fargate** | Worker service in private subnet (1 vCPU, 2GB RAM) |
| **NAT Gateway** | Outbound internet for Fargate tasks (Bedrock API calls) |
| **Amazon Bedrock** | Claude Sonnet 4.6 for medical transcript annotation |
| **DynamoDB** | Job status tracking (UPLOADING -> PROCESSING -> COMPLETED/FAILED) |
| **S3 (Results)** | Stores annotation JSON output (CORS-enabled for browser download) |
| **CloudWatch** | Logs from ECS worker + Lambda, alarms for auto-scaling |
| **Auto Scaling** | Step scaling on SQS queue depth (scale 0->1 when messages arrive) |

## Data Flow

1. **User authenticates** via Cognito User Pool (email/password)
2. **Uploads .docx** interview file directly to S3 via presigned URL
3. **S3 Event Notification** sends message to SQS Processing Queue
4. **ECS Worker** (Fargate) polls SQS, downloads the file from S3
5. **Worker calls Bedrock** (Claude Sonnet 4.6) — multi-pass annotation across 5 code groups
6. **Annotations saved** to S3 Results Bucket as JSON (504+ annotations per transcript)
7. **Job status updated** in DynamoDB (COMPLETED with results_key)
8. **User views/downloads results** via presigned URL from Results Bucket

## Deployment Requirements

- **AWS Account** with Bedrock model access enabled for Claude Sonnet 4.6
- **Region**: us-west-2 (required for Bedrock model availability)
- **CDK v2** (TypeScript/Python) for infrastructure deployment
- **Docker** for building the ECS worker container image
- **Node.js 18+** for frontend build

## Security

- All data in transit encrypted (HTTPS/TLS)
- S3 buckets have Block Public Access enabled
- ECS tasks run in private subnets (no direct internet exposure)
- API Gateway protected by Cognito authorizer
- IAM least-privilege for each service role

## Cost Drivers

- **Bedrock usage** (primary cost) — ~$3-8 per transcript depending on length
- **NAT Gateway** — hourly + data transfer charges
- **Fargate** — pay per second while processing (scales to 0 when idle)
- **S3/DynamoDB/SQS** — minimal at expected volume
