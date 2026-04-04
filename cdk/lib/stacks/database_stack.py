from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
)
from constructs import Construct


class DatabaseStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        project_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        removal = RemovalPolicy.DESTROY if env_name == "dev" else RemovalPolicy.RETAIN

        # ---------- sessions table ----------
        self.sessions_table = dynamodb.Table(
            self,
            "SessionsTable",
            table_name=f"{project_name}-{env_name}-sessions",
            partition_key=dynamodb.Attribute(
                name="session_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal,
            time_to_live_attribute="ttl",
        )
        self.sessions_table.add_global_secondary_index(
            index_name="user_id-index",
            partition_key=dynamodb.Attribute(
                name="user_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.NUMBER
            ),
        )

        # ---------- nodes table ----------
        self.nodes_table = dynamodb.Table(
            self,
            "NodesTable",
            table_name=f"{project_name}-{env_name}-nodes",
            partition_key=dynamodb.Attribute(
                name="node_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal,
        )
        self.nodes_table.add_global_secondary_index(
            index_name="session_id-index",
            partition_key=dynamodb.Attribute(
                name="session_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.NUMBER
            ),
        )

        # ---------- connections table (WebSocket) ----------
        self.connections_table = dynamodb.Table(
            self,
            "ConnectionsTable",
            table_name=f"{project_name}-{env_name}-connections",
            partition_key=dynamodb.Attribute(
                name="connection_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal,
            time_to_live_attribute="ttl",
        )

        # ---------- drawing_elements table (recursive verification) ----------
        self.drawing_elements_table = dynamodb.Table(
            self,
            "DrawingElementsTable",
            table_name=f"{project_name}-{env_name}-drawing-elements",
            partition_key=dynamodb.Attribute(
                name="drawing_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="element_seq", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal,
            time_to_live_attribute="ttl",
        )
        self.drawing_elements_table.add_global_secondary_index(
            index_name="drawing_id-confidence-index",
            partition_key=dynamodb.Attribute(
                name="drawing_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="confidence", type=dynamodb.AttributeType.NUMBER
            ),
        )

        # ---------- build_plans table (BuildPlan mode) ----------
        self.build_plans_table = dynamodb.Table(
            self,
            "BuildPlansTable",
            table_name=f"{project_name}-{env_name}-build-plans",
            partition_key=dynamodb.Attribute(
                name="plan_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal,
            time_to_live_attribute="ttl",
        )
        self.build_plans_table.add_global_secondary_index(
            index_name="session_id-index",
            partition_key=dynamodb.Attribute(
                name="session_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.NUMBER
            ),
        )

        # ---------- build_steps table (BuildPlan mode) ----------
        self.build_steps_table = dynamodb.Table(
            self,
            "BuildStepsTable",
            table_name=f"{project_name}-{env_name}-build-steps",
            partition_key=dynamodb.Attribute(
                name="plan_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="step_seq", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal,
            time_to_live_attribute="ttl",
        )
