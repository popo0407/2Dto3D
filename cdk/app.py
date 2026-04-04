#!/usr/bin/env python3
import aws_cdk as cdk

from lib.stacks.network_stack import NetworkStack
from lib.stacks.auth_stack import AuthStack
from lib.stacks.database_stack import DatabaseStack
from lib.stacks.lambda_stack import LambdaStack
from lib.stacks.pipeline_stack import PipelineStack
from lib.stacks.monitoring_stack import MonitoringStack

app = cdk.App()

env_name: str = app.node.try_get_context("environment") or "dev"
project_name = "2dto3d"
stack_prefix = f"Cad2d3d-{env_name}"

enable_fargate_ctx = app.node.try_get_context("enableFargate")
if enable_fargate_ctx is None:
    enable_fargate = env_name != "dev"
else:
    # cdk.json / --context の値は文字列またはboolの場合がある
    enable_fargate = str(enable_fargate_ctx).lower() not in ("false", "0", "no")

bedrock_region: str = app.node.try_get_context("bedrockRegion") or "ap-northeast-1"

aws_env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "ap-northeast-1",
)

# ---------- Stacks ----------

database_stack = DatabaseStack(
    app,
    f"{stack_prefix}-database",
    env_name=env_name,
    project_name=project_name,
    env=aws_env,
)

auth_stack = AuthStack(
    app,
    f"{stack_prefix}-auth",
    env_name=env_name,
    project_name=project_name,
    env=aws_env,
)

network_stack = NetworkStack(
    app,
    f"{stack_prefix}-network",
    env_name=env_name,
    project_name=project_name,
    env=aws_env,
)

lambda_stack = LambdaStack(
    app,
    f"{stack_prefix}-lambda",
    env_name=env_name,
    project_name=project_name,
    bedrock_region=bedrock_region,
    sessions_table=database_stack.sessions_table,
    nodes_table=database_stack.nodes_table,
    connections_table=database_stack.connections_table,
    uploads_bucket=network_stack.uploads_bucket,
    artifacts_bucket=network_stack.artifacts_bucket,
    previews_bucket=network_stack.previews_bucket,
    user_pool=auth_stack.user_pool,
    build_plans_table=database_stack.build_plans_table,
    build_steps_table=database_stack.build_steps_table,
    env=aws_env,
)
lambda_stack.add_dependency(database_stack)
lambda_stack.add_dependency(network_stack)
lambda_stack.add_dependency(auth_stack)

pipeline_stack = PipelineStack(
    app,
    f"{stack_prefix}-pipeline",
    env_name=env_name,
    project_name=project_name,
    bedrock_region=bedrock_region,
    sessions_table=database_stack.sessions_table,
    nodes_table=database_stack.nodes_table,
    connections_table=database_stack.connections_table,
    uploads_bucket=network_stack.uploads_bucket,
    artifacts_bucket=network_stack.artifacts_bucket,
    previews_bucket=network_stack.previews_bucket,
    websocket_api=lambda_stack.websocket_api,
    drawing_elements_table=database_stack.drawing_elements_table,
    enable_fargate=enable_fargate,
    env=aws_env,
)
pipeline_stack.add_dependency(lambda_stack)

monitoring_stack = MonitoringStack(
    app,
    f"{stack_prefix}-monitoring",
    env_name=env_name,
    project_name=project_name,
    env=aws_env,
)

app.synth()
