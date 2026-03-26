from aws_cdk import (
    Stack,
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_sns as sns,
    aws_cloudwatch_actions as cw_actions,
    CfnOutput,
)
from constructs import Construct


class MonitoringStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        project_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.alert_topic = sns.Topic(
            self,
            "AlertTopic",
            topic_name=f"{project_name}-{env_name}-alerts",
        )

        # Lambda error alarm (all functions)
        lambda_errors = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions_map={"FunctionName": f"{project_name}-{env_name}-*"},
            period=Duration.minutes(5),
            statistic="Sum",
        )

        cloudwatch.Alarm(
            self,
            "LambdaErrorAlarm",
            alarm_name=f"{project_name}-{env_name}-lambda-errors",
            metric=lambda_errors,
            threshold=5,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(cw_actions.SnsAction(self.alert_topic))

        # Step Functions execution failure alarm
        sfn_failed = cloudwatch.Metric(
            namespace="AWS/States",
            metric_name="ExecutionsFailed",
            dimensions_map={
                "StateMachineArn": f"arn:aws:states:{self.region}:{self.account}:stateMachine:{project_name}-{env_name}-cad-pipeline"
            },
            period=Duration.minutes(5),
            statistic="Sum",
        )

        cloudwatch.Alarm(
            self,
            "SfnFailureAlarm",
            alarm_name=f"{project_name}-{env_name}-sfn-failures",
            metric=sfn_failed,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(cw_actions.SnsAction(self.alert_topic))

        CfnOutput(self, "AlertTopicArn", value=self.alert_topic.topic_arn)
