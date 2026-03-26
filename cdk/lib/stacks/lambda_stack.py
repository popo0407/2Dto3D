from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as lambda_,
    aws_apigateway as apigw,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations_v2,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_cognito as cognito,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct


class LambdaStack(Stack):
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
        user_pool: cognito.UserPool,
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
        }

        # ---------- Common Layer ----------
        common_layer = lambda_.LayerVersion(
            self,
            "CommonLayer",
            layer_version_name=f"{project_name}-{env_name}-common",
            code=lambda_.Code.from_asset(
                "../backend",
                exclude=["tests/*", "functions/*", "*.pyc", "__pycache__"],
            ),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
        )

        # ---------- Lambda Functions ----------
        def create_function(
            name: str,
            handler: str = "index.lambda_handler",
            timeout_seconds: int = 30,
            memory_mb: int = 256,
            extra_env: dict | None = None,
        ) -> lambda_.Function:
            fn_env = {**common_env, **(extra_env or {})}
            fn = lambda_.Function(
                self,
                f"{name}Function",
                function_name=f"{project_name}-{env_name}-{name}",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler=handler,
                code=lambda_.Code.from_asset(f"../backend/functions/{name}"),
                layers=[common_layer],
                timeout=Duration.seconds(timeout_seconds),
                memory_size=memory_mb,
                environment=fn_env,
            )
            sessions_table.grant_read_write_data(fn)
            nodes_table.grant_read_write_data(fn)
            return fn

        # Queue name is deterministic — avoids circular cross-stack reference
        # (pipeline_stack already depends on lambda_stack for websocket_api)
        _queue_name = f"{project_name}-{env_name}-processing-queue"
        _queue_url = f"https://sqs.{self.region}.amazonaws.com/{self.account}/{_queue_name}"
        _queue_arn = f"arn:aws:sqs:{self.region}:{self.account}:{_queue_name}"

        upload_fn = create_function(
            "upload_handler",
            extra_env={"PROCESSING_QUEUE_URL": _queue_url},
        )
        upload_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[_queue_arn],
            )
        )
        uploads_bucket.grant_put(upload_fn)
        uploads_bucket.grant_read(upload_fn)

        history_fn = create_function("history_handler")

        chat_fn = create_function("chat_handler", timeout_seconds=60, memory_mb=512)
        if not use_mock_ai:
            chat_fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["bedrock:InvokeModel"],
                    resources=["*"],
                )
            )
        nodes_table.grant_read_write_data(chat_fn)
        artifacts_bucket.grant_read(chat_fn)

        # ---------- WebSocket API ----------
        ws_connect_fn = lambda_.Function(
            self,
            "WsConnectFunction",
            function_name=f"{project_name}-{env_name}-ws-connect",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.connect_handler",
            code=lambda_.Code.from_asset("../backend/functions/ws_handler"),
            layers=[common_layer],
            timeout=Duration.seconds(10),
            memory_size=128,
            environment=common_env,
        )
        connections_table.grant_read_write_data(ws_connect_fn)

        ws_disconnect_fn = lambda_.Function(
            self,
            "WsDisconnectFunction",
            function_name=f"{project_name}-{env_name}-ws-disconnect",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.disconnect_handler",
            code=lambda_.Code.from_asset("../backend/functions/ws_handler"),
            layers=[common_layer],
            timeout=Duration.seconds(10),
            memory_size=128,
            environment=common_env,
        )
        connections_table.grant_read_write_data(ws_disconnect_fn)

        ws_default_fn = lambda_.Function(
            self,
            "WsDefaultFunction",
            function_name=f"{project_name}-{env_name}-ws-default",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.default_handler",
            code=lambda_.Code.from_asset("../backend/functions/ws_handler"),
            layers=[common_layer],
            timeout=Duration.seconds(10),
            memory_size=128,
            environment=common_env,
        )
        connections_table.grant_read_write_data(ws_default_fn)

        self.websocket_api = apigwv2.WebSocketApi(
            self,
            "WebSocketApi",
            api_name=f"{project_name}-{env_name}-ws",
            connect_route_options=apigwv2.WebSocketRouteOptions(
                integration=integrations_v2.WebSocketLambdaIntegration(
                    "ConnectIntegration", ws_connect_fn
                ),
            ),
            disconnect_route_options=apigwv2.WebSocketRouteOptions(
                integration=integrations_v2.WebSocketLambdaIntegration(
                    "DisconnectIntegration", ws_disconnect_fn
                ),
            ),
            default_route_options=apigwv2.WebSocketRouteOptions(
                integration=integrations_v2.WebSocketLambdaIntegration(
                    "DefaultIntegration", ws_default_fn
                ),
            ),
        )

        ws_stage = apigwv2.WebSocketStage(
            self,
            "WebSocketStage",
            web_socket_api=self.websocket_api,
            stage_name=env_name,
            auto_deploy=True,
        )

        # ---------- REST API ----------
        rest_api = apigw.RestApi(
            self,
            "RestApi",
            rest_api_name=f"{project_name}-{env_name}-api",
            deploy_options=apigw.StageOptions(stage_name=env_name),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS if env_name == "dev" else [],
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self,
            "CognitoAuthorizer",
            cognito_user_pools=[user_pool],
        )
        auth_kwargs: dict = {"authorizer": authorizer}

        sessions_resource = rest_api.root.add_resource("sessions")
        sessions_resource.add_method(
            "POST", apigw.LambdaIntegration(upload_fn), **auth_kwargs
        )
        sessions_resource.add_method(
            "GET", apigw.LambdaIntegration(history_fn), **auth_kwargs
        )

        session_resource = sessions_resource.add_resource("{session_id}")
        session_resource.add_method(
            "GET", apigw.LambdaIntegration(history_fn), **auth_kwargs
        )
        session_resource.add_method(
            "DELETE", apigw.LambdaIntegration(history_fn), **auth_kwargs
        )

        upload_resource = session_resource.add_resource("upload")
        upload_resource.add_method(
            "POST", apigw.LambdaIntegration(upload_fn), **auth_kwargs
        )

        process_resource = session_resource.add_resource("process")
        process_resource.add_method(
            "POST", apigw.LambdaIntegration(upload_fn), **auth_kwargs
        )

        nodes_resource = session_resource.add_resource("nodes")
        nodes_resource.add_method(
            "GET", apigw.LambdaIntegration(history_fn), **auth_kwargs
        )

        node_resource = nodes_resource.add_resource("{node_id}")
        node_resource.add_method(
            "GET", apigw.LambdaIntegration(history_fn), **auth_kwargs
        )

        chat_resource = node_resource.add_resource("chat")
        chat_resource.add_method(
            "POST", apigw.LambdaIntegration(chat_fn), **auth_kwargs
        )

        revert_resource = node_resource.add_resource("revert")
        revert_resource.add_method(
            "POST", apigw.LambdaIntegration(history_fn), **auth_kwargs
        )

        download_resource = node_resource.add_resource("download")
        download_resource.add_method(
            "GET", apigw.LambdaIntegration(history_fn), **auth_kwargs
        )

        validate_resource = node_resource.add_resource("validate")
        validate_resource.add_method(
            "GET", apigw.LambdaIntegration(history_fn), **auth_kwargs
        )

        CfnOutput(self, "RestApiUrl", value=rest_api.url)
        CfnOutput(self, "WebSocketUrl", value=ws_stage.url)
