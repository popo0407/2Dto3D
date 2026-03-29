from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    CfnOutput,
)
from constructs import Construct


class NetworkStack(Stack):
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
        account_id = Stack.of(self).account

        # ---------- S3 Buckets ----------
        self.uploads_bucket = s3.Bucket(
            self,
            "UploadsBucket",
            bucket_name=f"{account_id}-{project_name}-{env_name}-uploads",
            removal_policy=removal,
            auto_delete_objects=env_name == "dev",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.POST],
                    allowed_origins=["*"] if env_name == "dev" else [],
                    allowed_headers=["*"],
                    max_age=3600,
                )
            ],
        )

        self.artifacts_bucket = s3.Bucket(
            self,
            "ArtifactsBucket",
            bucket_name=f"{account_id}-{project_name}-{env_name}-artifacts",
            removal_policy=removal,
            auto_delete_objects=env_name == "dev",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self.previews_bucket = s3.Bucket(
            self,
            "PreviewsBucket",
            bucket_name=f"{account_id}-{project_name}-{env_name}-previews",
            removal_policy=removal,
            auto_delete_objects=env_name == "dev",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.GET],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                    max_age=3600,
                )
            ],
        )

        # ---------- Frontend Bucket + CloudFront ----------
        self.frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"{account_id}-{project_name}-{env_name}-frontend",
            removal_policy=removal,
            auto_delete_objects=env_name == "dev",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    self.frontend_bucket,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                )
            ],
        )

        CfnOutput(
            self,
            "DistributionDomainName",
            value=self.distribution.distribution_domain_name,
        )
        CfnOutput(
            self, "UploadsBucketName", value=self.uploads_bucket.bucket_name
        )
        CfnOutput(
            self, "ArtifactsBucketName", value=self.artifacts_bucket.bucket_name
        )
