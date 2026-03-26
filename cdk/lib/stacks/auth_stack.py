from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_cognito as cognito,
    CfnOutput,
)
from constructs import Construct


class AuthStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        project_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"{project_name}-{env_name}-userpool",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            removal_policy=(
                RemovalPolicy.DESTROY if env_name == "dev" else RemovalPolicy.RETAIN
            ),
        )

        self.user_pool_client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name=f"{project_name}-{env_name}-webclient",
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
            generate_secret=False,
        )

        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(
            self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id
        )
