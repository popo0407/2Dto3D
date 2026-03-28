import os

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_lambda as lambda_,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_lambda_event_sources as event_sources,
    aws_apigatewayv2 as apigwv2,
    CfnOutput,
)
from constructs import Construct

from ..constructs.python_layer import prepare_common_layer_dir

_BACKEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../backend")
)


class PipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        project_name: str,
        use_mock_ai: bool,
        bedrock_region: str,
        sessions_table: dynamodb.Table,
        nodes_table: dynamodb.Table,
        connections_table: dynamodb.Table,
        uploads_bucket: s3.Bucket,
        artifacts_bucket: s3.Bucket,
        previews_bucket: s3.Bucket,
        websocket_api: apigwv2.WebSocketApi,
        enable_fargate: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        common_env = {
            "ENV_NAME": env_name,
            "PROJECT_NAME": project_name,
            "USE_MOCK_AI": "true" if use_mock_ai else "false",
            "BEDROCK_REGION": bedrock_region,
            "SESSIONS_TABLE": sessions_table.table_name,
            "NODES_TABLE": nodes_table.table_name,
            "CONNECTIONS_TABLE": connections_table.table_name,
            "UPLOADS_BUCKET": uploads_bucket.bucket_name,
            "ARTIFACTS_BUCKET": artifacts_bucket.bucket_name,
            "PREVIEWS_BUCKET": previews_bucket.bucket_name,
            "WEBSOCKET_API_ID": websocket_api.api_id,
        }

        # ---------- Common Layer ----------
        # Lambda Layers require Python modules under python/ in the zip so
        # the runtime can find them at /opt/python/.  We pre-build the
        # python/common/ structure and use that directory as the CDK asset.
        _layer_dir = prepare_common_layer_dir(_BACKEND_DIR)
        common_layer = lambda_.LayerVersion(
            self,
            "PipelineCommonLayer",
            layer_version_name=f"{project_name}-{env_name}-pipeline-common",
            code=lambda_.Code.from_asset(_layer_dir),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
        )

        bedrock_policy = iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "aws-marketplace:ViewSubscriptions",
                "aws-marketplace:Subscribe",
            ],
            resources=["*"],
        )

        def pipeline_lambda(
            name: str,
            timeout_seconds: int = 60,
            memory_mb: int = 512,
            extra_env: dict | None = None,
        ) -> lambda_.Function:
            fn_env = {**common_env, **(extra_env or {})}
            fn = lambda_.Function(
                self,
                f"{name}Function",
                function_name=f"{project_name}-{env_name}-{name}",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="index.lambda_handler",
                code=lambda_.Code.from_asset(f"../backend/functions/{name}"),
                layers=[common_layer],
                timeout=Duration.seconds(timeout_seconds),
                memory_size=memory_mb,
                environment=fn_env,
            )
            sessions_table.grant_read_write_data(fn)
            nodes_table.grant_read_write_data(fn)
            connections_table.grant_read_write_data(fn)
            uploads_bucket.grant_read(fn)
            artifacts_bucket.grant_read_write(fn)
            previews_bucket.grant_read_write(fn)
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["execute-api:ManageConnections"],
                    resources=[
                        f"arn:aws:execute-api:{self.region}:{self.account}:{websocket_api.api_id}/*"
                    ],
                )
            )
            return fn

        # Step 1: Parse handler
        parse_fn = pipeline_lambda("parse_handler", timeout_seconds=120, memory_mb=1024)

        # Step 2: AI Analyze handler
        ai_analyze_fn = pipeline_lambda(
            "ai_analyze_handler", timeout_seconds=300, memory_mb=1024
        )
        if not use_mock_ai:
            ai_analyze_fn.add_to_role_policy(bedrock_policy)

        # Step 4: Optimize handler
        optimize_fn = pipeline_lambda(
            "optimize_handler", timeout_seconds=120, memory_mb=1024
        )

        # Step 5: Validate handler
        validate_fn = pipeline_lambda("validate_handler", timeout_seconds=60)

        # Step 6: Notify handler
        notify_fn = pipeline_lambda(
            "notify_handler",
            timeout_seconds=30,
            memory_mb=256,
        )

        # ---------- Step 3: CadQuery Runner ----------
        # enable_fargate=True (prod): ECS Fargate で実際の CadQuery を実行する
        # enable_fargate=False (dev): Docker ビルド不要のモック Lambda でプレースホルダーを生成する
        if enable_fargate:
            vpc = ec2.Vpc(
                self,
                "PipelineVpc",
                vpc_name=f"{project_name}-{env_name}-pipeline-vpc",
                max_azs=2,
                nat_gateways=1,
                subnet_configuration=[
                    ec2.SubnetConfiguration(
                        name="Public",
                        subnet_type=ec2.SubnetType.PUBLIC,
                        cidr_mask=24,
                    ),
                ],
            )

            cluster = ecs.Cluster(
                self,
                "FargateCluster",
                cluster_name=f"{project_name}-{env_name}-cluster",
                vpc=vpc,
            )

            task_definition = ecs.FargateTaskDefinition(
                self,
                "CadQueryTaskDef",
                family=f"{project_name}-{env_name}-cadquery-runner",
                cpu=2048,
                memory_limit_mib=4096,
            )

            uploads_bucket.grant_read(task_definition.task_role)
            artifacts_bucket.grant_read_write(task_definition.task_role)
            previews_bucket.grant_read_write(task_definition.task_role)
            nodes_table.grant_read_write_data(task_definition.task_role)
            sessions_table.grant_read_write_data(task_definition.task_role)
            connections_table.grant_read_data(task_definition.task_role)
            task_definition.task_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["execute-api:ManageConnections"],
                    resources=[
                        f"arn:aws:execute-api:{self.region}:{self.account}:{websocket_api.api_id}/*"
                    ],
                )
            )

            log_group = logs.LogGroup(
                self,
                "CadQueryLogs",
                log_group_name=f"/ecs/{project_name}-{env_name}-cadquery-runner",
                removal_policy=RemovalPolicy.DESTROY,
                retention=logs.RetentionDays.TWO_WEEKS,
            )

            container = task_definition.add_container(
                "CadQueryContainer",
                container_name="cadquery-runner",
                image=ecs.ContainerImage.from_asset("../backend/functions/cadquery_runner"),
                logging=ecs.LogDrivers.aws_logs(
                    stream_prefix="cadquery", log_group=log_group
                ),
                environment={
                    **common_env,
                    "WEBSOCKET_API_ID": websocket_api.api_id,
                },
            )

            cadquery_step = tasks.EcsRunTask(
                self,
                "CadQueryStep",
                integration_pattern=sfn.IntegrationPattern.RUN_JOB,
                cluster=cluster,
                task_definition=task_definition,
                launch_target=tasks.EcsFargateLaunchTarget(
                    platform_version=ecs.FargatePlatformVersion.LATEST,
                ),
                assign_public_ip=True,
                container_overrides=[
                    tasks.ContainerOverride(
                        container_definition=container,
                        environment=[
                            tasks.TaskEnvironmentVariable(
                                name="SESSION_ID",
                                value=sfn.JsonPath.string_at("$.session_id"),
                            ),
                            tasks.TaskEnvironmentVariable(
                                name="NODE_ID",
                                value=sfn.JsonPath.string_at("$.node_id"),
                            ),
                        ],
                    )
                ],
                result_path="$.cadquery_result",
            )
        else:
            # dev: Docker ビルド不要のモック Lambda
            mock_cq_fn = pipeline_lambda(
                "mock_cadquery",
                timeout_seconds=30,
                memory_mb=256,
            )
            cadquery_step = tasks.LambdaInvoke(
                self,
                "CadQueryStep",
                lambda_function=mock_cq_fn,
                payload_response_only=True,
                result_path="$",
            )

        # ---------- Pipeline error notifier ----------
        # 任意のステップで例外が発生した場合にセッションを FAILED に更新し
        # WebSocket 経由でフロントエンドに PROCESSING_FAILED を通知する
        error_fn = pipeline_lambda(
            "pipeline_error_handler",
            timeout_seconds=30,
            memory_mb=256,
        )
        error_step = tasks.LambdaInvoke(
            self,
            "PipelineErrorStep",
            lambda_function=error_fn,
            payload_response_only=True,
            result_path="$",
        )
        fail_state = sfn.Fail(
            self,
            "PipelineFailed",
            cause="Pipeline processing error — see PipelineErrorStep logs",
        )
        error_step.next(fail_state)

        # ---------- Step Functions ----------
        # payload_response_only=True: Lambda の戻り値のみ取得（StatusCode等のラッパーを除去）
        # result_path="$": 状態全体をLambdaの戻り値で上書き（次ステップへ session_id/node_id を正しく引き継ぐ）
        parse_step = tasks.LambdaInvoke(
            self,
            "ParseStep",
            lambda_function=parse_fn,
            payload_response_only=True,
            result_path="$",
        )

        ai_analyze_step = tasks.LambdaInvoke(
            self,
            "AiAnalyzeStep",
            lambda_function=ai_analyze_fn,
            payload_response_only=True,
            result_path="$",
        )

        optimize_step = tasks.LambdaInvoke(
            self,
            "OptimizeStep",
            lambda_function=optimize_fn,
            payload_response_only=True,
            result_path="$",
        )

        validate_step = tasks.LambdaInvoke(
            self,
            "ValidateStep",
            lambda_function=validate_fn,
            payload_response_only=True,
            result_path="$",
        )

        notify_step = tasks.LambdaInvoke(
            self,
            "NotifyStep",
            lambda_function=notify_fn,
            payload_response_only=True,
            result_path="$",
        )

        # 全ステップでエラーをキャッチして WebSocket 経由でフロントエンドに通知
        for step_to_catch in [
            parse_step,
            ai_analyze_step,
            cadquery_step,
            optimize_step,
            validate_step,
            notify_step,
        ]:
            step_to_catch.add_catch(
                error_step,
                errors=["States.ALL"],
                result_path="$.error",
            )

        definition = (
            parse_step.next(ai_analyze_step)
            .next(cadquery_step)
            .next(optimize_step)
            .next(validate_step)
            .next(notify_step)
        )

        self.state_machine = sfn.StateMachine(
            self,
            "CadPipeline",
            state_machine_name=f"{project_name}-{env_name}-cad-pipeline",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.minutes(30),
        )

        # ---------- SQS Queue → Trigger Step Functions ----------
        self.processing_queue = sqs.Queue(
            self,
            "ProcessingQueue",
            queue_name=f"{project_name}-{env_name}-processing-queue",
            visibility_timeout=Duration.minutes(35),
        )

        queue_trigger_fn = lambda_.Function(
            self,
            "QueueTriggerFunction",
            function_name=f"{project_name}-{env_name}-queue-trigger",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.lambda_handler",
            code=lambda_.Code.from_inline(
                """
import json
import os
import boto3

sfn_client = boto3.client("stepfunctions")
STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]

def lambda_handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        sfn_client.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            input=json.dumps(body),
        )
    return {"statusCode": 200}
"""
            ),
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "STATE_MACHINE_ARN": self.state_machine.state_machine_arn,
            },
        )

        self.state_machine.grant_start_execution(queue_trigger_fn)
        queue_trigger_fn.add_event_source(
            event_sources.SqsEventSource(self.processing_queue, batch_size=1)
        )

        CfnOutput(
            self,
            "StateMachineArn",
            value=self.state_machine.state_machine_arn,
        )
        CfnOutput(
            self,
            "ProcessingQueueUrl",
            value=self.processing_queue.queue_url,
        )
