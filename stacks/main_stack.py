import os
from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    CfnOutput,
    aws_cognito as cognito,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    aws_sqs as sqs,
    aws_ec2 as ec2,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3_notifications as s3n,
    aws_applicationautoscaling as appscaling,
    aws_logs as logs,
    aws_bedrock as bedrock,
)
from constructs import Construct


class MainStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # === Cognito ===
        user_pool = cognito.UserPool(
            self, "UserPool",
            user_pool_name="p8-annotation-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        user_pool_client = user_pool.add_client(
            "WebClient",
            auth_flows=cognito.AuthFlow(user_srp=True, user_password=True),
        )

        # === S3 Buckets ===
        uploads_bucket = s3.Bucket(
            self, "UploadsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            cors=[s3.CorsRule(
                allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.GET],
                allowed_origins=["*"],
                allowed_headers=["*"],
                max_age=3600,
            )],
        )

        results_bucket = s3.Bucket(
            self, "ResultsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            cors=[s3.CorsRule(
                allowed_headers=["*"],
                allowed_methods=[s3.HttpMethods.GET],
                allowed_origins=["*"],
            )],
        )

        frontend_bucket = s3.Bucket(
            self, "FrontendBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # === DynamoDB ===
        jobs_table = dynamodb.Table(
            self, "JobsTable",
            table_name="p8-annotation-jobs",
            partition_key=dynamodb.Attribute(name="job_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            time_to_live_attribute="ttl",
        )
        jobs_table.add_global_secondary_index(
            index_name="user-index",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="created_at", type=dynamodb.AttributeType.STRING),
        )

        # === SQS ===
        dlq = sqs.Queue(self, "ProcessingDLQ", retention_period=Duration.days(14))
        processing_queue = sqs.Queue(
            self, "ProcessingQueue",
            visibility_timeout=Duration.minutes(10),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )

        # === Bedrock PHI Guardrail ===
        # Caregiver interview transcripts may contain protected health
        # information. This guardrail runs the PII/PHI entity detectors in
        # DETECT mode (action NONE): every detection is reported in the
        # Bedrock trace, but nothing is blocked or masked. We deliberately do
        # NOT anonymize -- the pipeline relies on AGE per annotation for the
        # age-stratified analysis, and masking would also corrupt the
        # transcript text the model annotates against. Flagging keeps the tool
        # safe to point at non-anonymized data while preserving the signal the
        # analysis needs. Switch an entity's action to BLOCK/ANONYMIZE here if
        # 8p's compliance posture later requires it.
        phi_pii_types = [
            "NAME", "EMAIL", "PHONE", "ADDRESS", "AGE", "USERNAME",
            "US_SOCIAL_SECURITY_NUMBER", "US_PASSPORT_NUMBER", "DRIVER_ID",
            "CA_HEALTH_NUMBER", "UK_NATIONAL_HEALTH_SERVICE_NUMBER",
        ]
        guardrail = bedrock.CfnGuardrail(
            self, "PHIGuardrail",
            name="p8-phi-detection",
            description="Detects (flags, does not block) PII/PHI in interview transcripts.",
            blocked_input_messaging="Input blocked by P8 content policy.",
            blocked_outputs_messaging="Output blocked by P8 content policy.",
            sensitive_information_policy_config=bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                pii_entities_config=[
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(
                        type=pii_type,
                        action="NONE",
                    )
                    for pii_type in phi_pii_types
                ],
            ),
        )
        guardrail_version = bedrock.CfnGuardrailVersion(
            self, "PHIGuardrailVersion",
            guardrail_identifier=guardrail.attr_guardrail_id,
        )

        # === VPC ===
        vpc = ec2.Vpc(
            self, "ProcessingVpc",
            # Use the first 2 AZs of whatever region the stack deploys into,
            # rather than hardcoding us-west-2a/b -- keeps the stack portable
            # to any account/region for the 8p handoff.
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(name="Private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=24),
            ],
        )

        # === ECS Fargate Processing ===
        cluster = ecs.Cluster(self, "ProcessingCluster", vpc=vpc)

        task_def = ecs.FargateTaskDefinition(
            self, "WorkerTask",
            cpu=1024,
            memory_limit_mib=2048,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.X86_64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        task_def.task_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
                "bedrock:Converse",
                "bedrock:ConverseStream",
                "bedrock:ApplyGuardrail",
            ],
            resources=["*"],
        ))
        task_def.task_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "aws-marketplace:ViewSubscriptions",
                "aws-marketplace:Subscribe",
            ],
            resources=["*"],
        ))
        uploads_bucket.grant_read(task_def.task_role)
        results_bucket.grant_read_write(task_def.task_role)
        jobs_table.grant_read_write_data(task_def.task_role)
        processing_queue.grant_consume_messages(task_def.task_role)

        processing_dir = os.path.join(os.path.dirname(__file__), "..", "processing")
        task_def.add_container(
            "Worker",
            image=ecs.ContainerImage.from_asset(processing_dir),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="p8-worker",
                log_retention=logs.RetentionDays.TWO_WEEKS,
            ),
            environment={
                "QUEUE_URL": processing_queue.queue_url,
                "UPLOADS_BUCKET": uploads_bucket.bucket_name,
                "RESULTS_BUCKET": results_bucket.bucket_name,
                "JOBS_TABLE": jobs_table.table_name,
                # The worker authenticates to Bedrock via its Fargate task role
                # (granted bedrock:InvokeModel below). Do NOT inject a personal
                # AWS_BEARER_TOKEN_BEDROCK here -- utils/bedrock.py falls back to
                # role-based boto3 credentials when the token is unset, which is
                # what makes this stack portable to any AWS account.
                "BEDROCK_REGION": self.region,
                # PHI guardrail (detect mode). When set, every Bedrock call
                # runs through this guardrail so PII/PHI detections show up in
                # the trace. utils/bedrock.py no-ops if these are unset, so
                # local/Streamlit runs are unaffected.
                "BEDROCK_GUARDRAIL_ID": guardrail.attr_guardrail_id,
                "BEDROCK_GUARDRAIL_VERSION": guardrail_version.attr_version,
            },
        )

        fargate_service = ecs.FargateService(
            self, "WorkerService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=0,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
        )

        scaling = fargate_service.auto_scale_task_count(min_capacity=0, max_capacity=5)
        scaling.scale_on_metric(
            "QueueDepthScaling",
            metric=processing_queue.metric_approximate_number_of_messages_visible(),
            scaling_steps=[
                appscaling.ScalingInterval(upper=0, change=-5),
                appscaling.ScalingInterval(lower=1, change=1),
                appscaling.ScalingInterval(lower=5, change=2),
            ],
            adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
        )

        # S3 upload -> SQS
        uploads_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(processing_queue),
            s3.NotificationKeyFilter(prefix="uploads/"),
        )

        # === Lambda Functions ===
        lambda_env = {
            "UPLOADS_BUCKET": uploads_bucket.bucket_name,
            "RESULTS_BUCKET": results_bucket.bucket_name,
            "JOBS_TABLE": jobs_table.table_name,
        }
        lambdas_dir = os.path.join(os.path.dirname(__file__), "..", "lambdas")

        presigned_url_fn = _lambda.Function(
            self, "PresignedUrlFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset(os.path.join(lambdas_dir, "presigned_url")),
            environment=lambda_env,
            timeout=Duration.seconds(10),
        )
        uploads_bucket.grant_put(presigned_url_fn)
        jobs_table.grant_read_write_data(presigned_url_fn)

        job_status_fn = _lambda.Function(
            self, "JobStatusFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset(os.path.join(lambdas_dir, "job_status")),
            environment=lambda_env,
            timeout=Duration.seconds(10),
        )
        jobs_table.grant_read_data(job_status_fn)

        get_results_fn = _lambda.Function(
            self, "GetResultsFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset(os.path.join(lambdas_dir, "get_results")),
            environment=lambda_env,
            timeout=Duration.seconds(10),
        )
        results_bucket.grant_read(get_results_fn)
        jobs_table.grant_read_data(get_results_fn)

        list_jobs_fn = _lambda.Function(
            self, "ListJobsFn",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset(os.path.join(lambdas_dir, "list_jobs")),
            environment=lambda_env,
            timeout=Duration.seconds(10),
        )
        jobs_table.grant_read_data(list_jobs_fn)

        # === API Gateway ===
        api = apigw.RestApi(
            self, "AnnotationApi",
            rest_api_name="P8 Annotation API",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "CognitoAuthorizer",
            cognito_user_pools=[user_pool],
        )
        auth_kwargs = {
            "authorizer": authorizer,
            "authorization_type": apigw.AuthorizationType.COGNITO,
        }

        uploads_resource = api.root.add_resource("uploads")
        uploads_resource.add_method("POST", apigw.LambdaIntegration(presigned_url_fn), **auth_kwargs)

        jobs_resource = api.root.add_resource("jobs")
        jobs_resource.add_method("GET", apigw.LambdaIntegration(list_jobs_fn), **auth_kwargs)

        job_resource = jobs_resource.add_resource("{id}")
        job_resource.add_resource("status").add_method("GET", apigw.LambdaIntegration(job_status_fn), **auth_kwargs)
        job_resource.add_resource("results").add_method("GET", apigw.LambdaIntegration(get_results_fn), **auth_kwargs)

        # === CloudFront ===
        distribution = cloudfront.Distribution(
            self, "FrontendDist",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(frontend_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404, response_http_status=200,
                    response_page_path="/index.html", ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=403, response_http_status=200,
                    response_page_path="/index.html", ttl=Duration.seconds(0),
                ),
            ],
        )

        # === Outputs ===
        CfnOutput(self, "CloudFrontURLOutput", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "ApiURLOutput", value=api.url)
        CfnOutput(self, "UserPoolIdOutput", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientIdOutput", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "UploadsBucketOutput", value=uploads_bucket.bucket_name)
        CfnOutput(self, "ResultsBucketOutput", value=results_bucket.bucket_name)
        CfnOutput(self, "GuardrailIdOutput", value=guardrail.attr_guardrail_id)
