#!/usr/bin/env python3
import os
import aws_cdk as cdk
from stacks.main_stack import MainStack
from stacks.integrated_stack import IntegratedStack

app = cdk.App()

# Account/region are resolved in this order so the stack deploys into ANY
# account without editing code (required for the 8p hosting handoff):
#   1. CDK context:  cdk deploy -c account=123456789012 -c region=us-west-2
#   2. Standard CDK env vars: CDK_DEPLOY_ACCOUNT / CDK_DEPLOY_REGION
#   3. The credentials the CLI is currently using: CDK_DEFAULT_ACCOUNT / CDK_DEFAULT_REGION
account = (
    app.node.try_get_context("account")
    or os.environ.get("CDK_DEPLOY_ACCOUNT")
    or os.environ.get("CDK_DEFAULT_ACCOUNT")
)
region = (
    app.node.try_get_context("region")
    or os.environ.get("CDK_DEPLOY_REGION")
    or os.environ.get("CDK_DEFAULT_REGION")
    or "us-west-2"  # Bedrock model availability
)

env = cdk.Environment(account=account, region=region)

# Original stack (deployed, left untouched). Kept so it still synthesizes; the
# integrated stack below is the new parallel system we deploy going forward.
MainStack(app, "P8AnnotationStack", env=env)

# New integrated, category-driven system. Deploys ALONGSIDE the original with
# independent (auto-generated) resource names, so there are no collisions in
# the same account.
IntegratedStack(app, "P8IntegratedStack", env=env)

app.synth()
