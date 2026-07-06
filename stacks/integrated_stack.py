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


class IntegratedStack(Stack):
    """
    The integrated, category-driven P8 system. Deployed as a NEW stack ALONGSIDE
    the original P8AnnotationStack -- it does not touch any existing resource.

    The spine is a single predictions table: every annotation the pipeline
    produces becomes one row tagged with a category and a review status. The
    upload flow tags a category, the worker writes prediction rows, and the
    review view + visualizations are just queries over this one table.

    All physical names are CloudFormation-auto-generated (no hardcoded
    table_name / user_pool_name like the original stack) so this stack can be
    deployed in the SAME account as the original without name collisions.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # === Cognito ===
        user_pool = cognito.UserPool(
            self, "UserPool",
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

        # === DynamoDB: jobs (one row per uploaded interview) ===
        jobs_table = dynamodb.Table(
            self, "JobsTable",
            partition_key=dynamodb.Attribute(name="job_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        jobs_table.add_global_secondary_index(
            index_name="category-index",
            partition_key=dynamodb.Attribute(name="category", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="created_at", type=dynamodb.AttributeType.STRING),
        )
        # list_jobs queries this to show a user their own uploads, newest first.
        jobs_table.add_global_secondary_index(
            index_name="user-index",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="created_at", type=dynamodb.AttributeType.STRING),
        )

        # === DynamoDB: categories (the disease/mutation groups) ===
        # Tiny table: one item per category name. "Choose existing or create
        # new" on upload reads/writes here. Same standard codebook for all.
        categories_table = dynamodb.Table(
            self, "CategoriesTable",
            partition_key=dynamodb.Attribute(name="category", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # === DynamoDB: predictions (THE SPINE -- one row per annotation) ===
        # PK = category, SK = "interview_id#idx". idx is the position of the
        # annotation within the interview's prediction list -- this matches the
        # legacy review key convention ("Caregiver 11_49") so migrated reviews
        # attach to the right prediction. Each row carries the concept, quote,
        # age, rationale, a review status, and the reviewer vote lists.
        predictions_table = dynamodb.Table(
            self, "PredictionsTable",
            partition_key=dynamodb.Attribute(name="category", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="prediction_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        # Query "pending/approved predictions in category X" for the review
        # queue and the visualizations.
        predictions_table.add_global_secondary_index(
            index_name="category-status-index",
            partition_key=dynamodb.Attribute(name="category", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="status", type=dynamodb.AttributeType.STRING),
        )

        # === SQS ===
        dlq = sqs.Queue(self, "ProcessingDLQ", retention_period=Duration.days(14))
        processing_queue = sqs.Queue(
            self, "ProcessingQueue",
            visibility_timeout=Duration.minutes(10),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )

        # === Bedrock PHI Guardrail (used ONLY by the upload-time PII scan) ===
        # The worker calls ApplyGuardrail (source=INPUT) on each uploaded
        # transcript to detect DIRECT identifiers before annotating; it reads
        # the assessment and rejects the job itself. This guardrail is NOT
        # attached to any model invocation, so its block/detect actions are
        # irrelevant -- we only consume the reported piiEntities.
        phi_pii_types = [
            "NAME", "EMAIL", "PHONE", "ADDRESS", "AGE", "USERNAME",
            "US_SOCIAL_SECURITY_NUMBER", "US_PASSPORT_NUMBER", "DRIVER_ID",
            "CA_HEALTH_NUMBER", "UK_NATIONAL_HEALTH_SERVICE_NUMBER",
        ]
        guardrail = bedrock.CfnGuardrail(
            self, "PHIGuardrail",
            name=f"{construct_id}-phi-detection",
            description="Detects (flags, does not block) PII/PHI in interview transcripts.",
            blocked_input_messaging="Input blocked by content policy.",
            blocked_outputs_messaging="Output blocked by content policy.",
            sensitive_information_policy_config=bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                pii_entities_config=[
                    # action="NONE" alone is NOT enough: input_action defaults to
                    # BLOCK, so any transcript mentioning an AGE/NAME (every one of
                    # ours) gets the whole request blocked (stopReason=
                    # guardrail_intervened), silently zeroing out annotations. We
                    # must explicitly set input/output actions to NONE so the
                    # guardrail only flags/detects and never blocks.
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(
                        type=t,
                        action="NONE",
                        input_action="NONE",
                        output_action="NONE",
                        input_enabled=True,
                        output_enabled=True,
                    )
                    for t in phi_pii_types
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
            actions=["aws-marketplace:ViewSubscriptions", "aws-marketplace:Subscribe"],
            resources=["*"],
        ))
        uploads_bucket.grant_read(task_def.task_role)
        results_bucket.grant_read_write(task_def.task_role)
        jobs_table.grant_read_write_data(task_def.task_role)
        predictions_table.grant_read_write_data(task_def.task_role)
        processing_queue.grant_consume_messages(task_def.task_role)

        processing_dir = os.path.join(os.path.dirname(__file__), "..", "processing")
        task_def.add_container(
            "Worker",
            image=ecs.ContainerImage.from_asset(processing_dir),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="p8-integrated-worker",
                log_retention=logs.RetentionDays.TWO_WEEKS,
            ),
            environment={
                "QUEUE_URL": processing_queue.queue_url,
                "UPLOADS_BUCKET": uploads_bucket.bucket_name,
                "RESULTS_BUCKET": results_bucket.bucket_name,
                "JOBS_TABLE": jobs_table.table_name,
                "PREDICTIONS_TABLE": predictions_table.table_name,
                "BEDROCK_REGION": self.region,
                # Consumed by the upload-time PII scan (utils/pii_scan.py), not
                # by any converse/annotation call.
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
        uploads_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(processing_queue),
            s3.NotificationKeyFilter(prefix="uploads/"),
        )

        # === Lambda Functions ===
        lambdas_dir = os.path.join(os.path.dirname(__file__), "..", "lambdas")
        common_env = {
            "UPLOADS_BUCKET": uploads_bucket.bucket_name,
            "RESULTS_BUCKET": results_bucket.bucket_name,
            "JOBS_TABLE": jobs_table.table_name,
            "PREDICTIONS_TABLE": predictions_table.table_name,
            "CATEGORIES_TABLE": categories_table.table_name,
        }

        def make_fn(name, folder, timeout=10):
            return _lambda.Function(
                self, name,
                runtime=_lambda.Runtime.PYTHON_3_11,
                handler="handler.handler",
                code=_lambda.Code.from_asset(os.path.join(lambdas_dir, folder)),
                environment=common_env,
                timeout=Duration.seconds(timeout),
            )

        presigned_url_fn = make_fn("PresignedUrlFn", "presigned_url")
        uploads_bucket.grant_put(presigned_url_fn)
        jobs_table.grant_read_write_data(presigned_url_fn)
        categories_table.grant_read_write_data(presigned_url_fn)

        job_status_fn = make_fn("JobStatusFn", "job_status")
        jobs_table.grant_read_data(job_status_fn)

        get_results_fn = make_fn("GetResultsFn", "get_results")
        results_bucket.grant_read(get_results_fn)
        jobs_table.grant_read_data(get_results_fn)

        # Resolves a job paused in PII_REVIEW: proceed (re-enqueue) or cancel.
        pii_decision_fn = make_fn("PiiDecisionFn", "pii_decision")
        pii_decision_fn.add_environment("QUEUE_URL", processing_queue.queue_url)
        jobs_table.grant_read_write_data(pii_decision_fn)
        uploads_bucket.grant_delete(pii_decision_fn)
        processing_queue.grant_send_messages(pii_decision_fn)

        list_jobs_fn = make_fn("ListJobsFn", "list_jobs")
        jobs_table.grant_read_data(list_jobs_fn)

        # New integration lambdas (handlers added in later steps).
        categories_fn = make_fn("CategoriesFn", "categories")
        categories_table.grant_read_write_data(categories_fn)

        list_predictions_fn = make_fn("ListPredictionsFn", "list_predictions")
        predictions_table.grant_read_data(list_predictions_fn)

        vote_fn = make_fn("VoteFn", "vote")
        predictions_table.grant_read_write_data(vote_fn)

        list_interviews_fn = make_fn("ListInterviewsFn", "list_interviews")
        predictions_table.grant_read_data(list_interviews_fn)

        # Aggregate endpoint feeding the visualizations: groups a category's
        # predictions into concept frequencies / quotes / per-interview sets,
        # applying the "counts until rejected" rule.
        aggregate_fn = make_fn("AggregateFn", "aggregate", timeout=30)
        predictions_table.grant_read_data(aggregate_fn)

        # === API Gateway ===
        api = apigw.RestApi(
            self, "AnnotationApi",
            rest_api_name=f"{construct_id} API",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"],
            ),
        )
        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "CognitoAuthorizer", cognito_user_pools=[user_pool],
        )
        auth = {"authorizer": authorizer, "authorization_type": apigw.AuthorizationType.COGNITO}

        uploads_resource = api.root.add_resource("uploads")
        uploads_resource.add_method("POST", apigw.LambdaIntegration(presigned_url_fn), **auth)

        categories_resource = api.root.add_resource("categories")
        categories_resource.add_method("GET", apigw.LambdaIntegration(categories_fn), **auth)
        categories_resource.add_method("POST", apigw.LambdaIntegration(categories_fn), **auth)

        jobs_resource = api.root.add_resource("jobs")
        jobs_resource.add_method("GET", apigw.LambdaIntegration(list_jobs_fn), **auth)
        job_resource = jobs_resource.add_resource("{id}")
        job_resource.add_resource("status").add_method("GET", apigw.LambdaIntegration(job_status_fn), **auth)
        job_resource.add_resource("results").add_method("GET", apigw.LambdaIntegration(get_results_fn), **auth)
        job_resource.add_resource("pii-decision").add_method("POST", apigw.LambdaIntegration(pii_decision_fn), **auth)

        predictions_resource = api.root.add_resource("predictions")
        predictions_resource.add_method("GET", apigw.LambdaIntegration(list_predictions_fn), **auth)
        prediction_resource = predictions_resource.add_resource("{id}")
        prediction_resource.add_resource("vote").add_method("POST", apigw.LambdaIntegration(vote_fn), **auth)

        interviews_resource = api.root.add_resource("interviews")
        interviews_resource.add_method("GET", apigw.LambdaIntegration(list_interviews_fn), **auth)

        aggregate_resource = api.root.add_resource("aggregate")
        aggregate_resource.add_method("GET", apigw.LambdaIntegration(aggregate_fn), **auth)

        # === CloudFront ===
        distribution = cloudfront.Distribution(
            self, "FrontendDist",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(frontend_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(http_status=404, response_http_status=200, response_page_path="/index.html", ttl=Duration.seconds(0)),
                cloudfront.ErrorResponse(http_status=403, response_http_status=200, response_page_path="/index.html", ttl=Duration.seconds(0)),
            ],
        )

        # === Outputs ===
        CfnOutput(self, "CloudFrontURLOutput", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "ApiURLOutput", value=api.url)
        CfnOutput(self, "UserPoolIdOutput", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientIdOutput", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "FrontendBucketOutput", value=frontend_bucket.bucket_name)
        CfnOutput(self, "UploadsBucketOutput", value=uploads_bucket.bucket_name)
        CfnOutput(self, "ResultsBucketOutput", value=results_bucket.bucket_name)
        CfnOutput(self, "PredictionsTableOutput", value=predictions_table.table_name)
        CfnOutput(self, "CategoriesTableOutput", value=categories_table.table_name)
        CfnOutput(self, "GuardrailIdOutput", value=guardrail.attr_guardrail_id)
