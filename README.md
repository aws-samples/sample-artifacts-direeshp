# AWS Application Migration Service (MGN) Initializer

Terraform pattern to automatically initialize AWS Application Migration Service (MGN) in any AWS region with a Lambda function.

## Overview

This pattern deploys a Lambda function that fully initializes MGN service including:

1. **IAM Role Verification** - Scans existing IAM roles and Service-Linked Role (SLR)
2. **Policy Compliance** - Verifies all required policies are attached, fixes if missing
3. **Role Creation** - Creates any missing MGN IAM roles with proper trust policies
4. **MGN Initialization** - Initializes the MGN service in the target region
5. **Replication Template** - Configures replication settings with VPC auto-discovery
6. **Launch Template** - Configures launch settings with post-launch actions enabled

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Terraform     │────▶│  Lambda Function │────▶│   MGN Service   │
│   (Deploy)      │     │  (Initializer)   │     │   (Configured)  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │   IAM Roles     │
                        │   (6 roles)     │
                        └─────────────────┘
```

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform >= 1.0.0
- AWS account with permissions to create IAM roles and Lambda functions

## Quick Start

1. Clone this repository

2. Copy the example tfvars file:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```

3. Edit `terraform.tfvars` with your desired region:
   ```hcl
   aws_region = "eu-west-1"
   ```

4. Initialize and deploy:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

## Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `aws_region` | AWS region to deploy MGN | Required |
| `staging_subnet_id` | Subnet for replication servers | Auto-discovered |
| `security_group_ids` | Security groups for replication | Auto-discovered |
| `replication_instance_type` | Instance type for replication servers | `t3.small` |
| `data_plane_routing` | Data plane routing method | `PRIVATE_IP` |
| `create_public_ip` | Create public IP for replication servers | `false` |

See `variables.tf` for all available options.

## IAM Roles Created

The Lambda function creates/verifies these MGN roles:

- `AWSApplicationMigrationReplicationServerRole`
- `AWSApplicationMigrationConversionServerRole`
- `AWSApplicationMigrationMGHRole`
- `AWSApplicationMigrationLaunchInstanceWithDrsRole`
- `AWSApplicationMigrationLaunchInstanceWithSsmRole`
- `AWSApplicationMigrationAgentRole`

## Outputs

| Output | Description |
|--------|-------------|
| `lambda_function_arn` | ARN of the MGN initializer Lambda |
| `lambda_function_name` | Name of the Lambda function |
| `mgn_initialization_result` | Result of MGN initialization |

## Multi-Region Deployment

To deploy to multiple regions, simply change the `aws_region` variable and run `terraform apply` again:

```bash
# Deploy to eu-west-1
echo 'aws_region = "eu-west-1"' > terraform.tfvars
terraform apply

# Deploy to us-east-1
echo 'aws_region = "us-east-1"' > terraform.tfvars  
terraform apply
```

## Cleanup

```bash
terraform destroy
```

Note: This only removes the Lambda function and related resources. MGN service initialization and IAM roles persist.

## License

See LICENSE.txt
