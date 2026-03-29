import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    env_name: str
    project_name: str
    bedrock_region: str
    sessions_table: str
    nodes_table: str
    connections_table: str
    uploads_bucket: str
    artifacts_bucket: str
    previews_bucket: str


def get_config() -> AppConfig:
    return AppConfig(
        env_name=os.environ.get("ENV_NAME", "dev"),
        project_name=os.environ.get("PROJECT_NAME", "2dto3d"),
        bedrock_region=os.environ.get("BEDROCK_REGION", "ap-northeast-1"),
        sessions_table=os.environ.get("SESSIONS_TABLE", "2dto3d-dev-sessions"),
        nodes_table=os.environ.get("NODES_TABLE", "2dto3d-dev-nodes"),
        connections_table=os.environ.get("CONNECTIONS_TABLE", "2dto3d-dev-connections"),
        uploads_bucket=os.environ.get("UPLOADS_BUCKET", ""),
        artifacts_bucket=os.environ.get("ARTIFACTS_BUCKET", ""),
        previews_bucket=os.environ.get("PREVIEWS_BUCKET", ""),
    )
