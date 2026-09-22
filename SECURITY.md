# Security

## Reporting Security Issues

If you discover a potential security issue in this project, we ask that you notify AWS/Amazon Security via our
[vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create
a public GitHub issue.

## Production Hardening Recommendations

This pattern is designed as a sample for initializing AWS Application Migration Service (AWS MGN). When deploying
in production environments, consider the following security enhancements:

### CloudWatch Logs Encryption

The CloudWatch log group created by this pattern uses AWS-managed encryption by default. For production workloads
with sensitive data requirements, enable encryption with a customer-managed AWS KMS key:

```hcl
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = "arn:aws:kms:REGION:ACCOUNT:key/KEY-ID"
}
```

### Lambda Function Hardening

- **VPC deployment**: This Lambda function makes API calls only (no VPC resource access required). If your
  organization requires Lambda functions to run within a VPC, add VPC configuration to the Lambda resource.
- **Dead Letter Queue (DLQ)**: The Lambda is invoked synchronously by Terraform. A DLQ is not required for
  synchronous invocations but can be added for additional error tracking.
- **Reserved concurrency**: Consider setting reserved concurrency to 1 since this function should only run
  once per deployment.
- **Code signing**: For production deployments, consider enabling Lambda code signing to ensure only trusted
  code is deployed.

### Network Security

- Use `data_plane_routing = "PRIVATE_IP"` to keep replication traffic within your VPC.
- Set `create_public_ip = false` to prevent public IP assignment to replication servers.
- Restrict security groups to allow only necessary replication traffic (TCP 1500 for data replication, TCP 443 for API calls).

### IAM Permissions

The Lambda execution role follows least-privilege principles with scoped resource ARNs. Review and adjust
permissions based on your organization's security requirements:

- MGN and EC2 operations use `Resource: "*"` because these APIs do not support resource-level permissions.
- IAM operations are scoped to `AWSApplicationMigration*` role name prefix.
- Service-linked role creation is restricted to `mgn.amazonaws.com` via IAM condition key.

### Encryption

- Consider using a customer-managed AWS KMS key for EBS encryption by providing a `kms_key_arn` value.
- Ensure the KMS key policy grants appropriate permissions to the MGN service-linked role.
