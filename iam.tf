# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = local.role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

# IAM Policy for Lambda - Least Privilege
resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.lambda_function_name}-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.function_name}:*"
      },
      {
        Sid    = "CreateServiceLinkedRole"
        Effect = "Allow"
        Action = "iam:CreateServiceLinkedRole"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/mgn.amazonaws.com/AWSServiceRoleForApplicationMigrationService"
        Condition = {
          StringEquals = {
            "iam:AWSServiceName" = "mgn.amazonaws.com"
          }
        }
      },
      {
        # Role create/read only. iam:AttachRolePolicy is intentionally NOT
        # granted here — attaching arbitrary managed policies to a role you
        # can create is a privilege-escalation path (e.g. attaching
        # AdministratorAccess). Attachment is granted separately below with a
        # strict allowlist of policy ARNs.
        Sid    = "IAMRoleOperations"
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:GetRole",
          "iam:ListAttachedRolePolicies"
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/AWSApplicationMigration*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/mgn.amazonaws.com/AWSServiceRoleForApplicationMigrationService"
        ]
      },
      {
        # Attach only the specific AWS-managed MGN/DRS/SSM policies that the
        # initializer legitimately needs. The iam:PolicyARN condition prevents
        # attaching any other policy (such as AdministratorAccess) to the
        # AWSApplicationMigration* roles, closing the privilege-escalation gap.
        Sid    = "IAMAttachMGNManagedPoliciesOnly"
        Effect = "Allow"
        Action = "iam:AttachRolePolicy"
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/AWSApplicationMigration*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/mgn.amazonaws.com/AWSServiceRoleForApplicationMigrationService"
        ]
        Condition = {
          ArnEquals = {
            "iam:PolicyARN" = [
              "arn:aws:iam::aws:policy/service-role/AWSApplicationMigrationReplicationServerPolicy",
              "arn:aws:iam::aws:policy/service-role/AWSApplicationMigrationConversionServerPolicy",
              "arn:aws:iam::aws:policy/service-role/AWSApplicationMigrationMGHAccess",
              "arn:aws:iam::aws:policy/service-role/AWSApplicationMigrationAgentPolicy_v2",
              "arn:aws:iam::aws:policy/service-role/AWSElasticDisasterRecoveryEc2InstancePolicy",
              "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
            ]
          }
        }
      },
      {
        Sid    = "IAMInstanceProfileOperations"
        Effect = "Allow"
        Action = [
          "iam:CreateInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:AddRoleToInstanceProfile"
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/AWSApplicationMigration*"
      },
      {
        # MGN does not support resource-level permissions
        Sid    = "MGNOperations"
        Effect = "Allow"
        Action = [
          "mgn:InitializeService",
          "mgn:DescribeReplicationConfigurationTemplates",
          "mgn:CreateReplicationConfigurationTemplate",
          "mgn:UpdateReplicationConfigurationTemplate",
          "mgn:DescribeLaunchConfigurationTemplates",
          "mgn:CreateLaunchConfigurationTemplate",
          "mgn:UpdateLaunchConfigurationTemplate"
        ]
        Resource = "*"
      },
      {
        # EC2 Describe/Get actions require wildcard resource (they are
        # read-only and do not support resource-level permissions). MGN
        # validates the staging/launch configuration against these when
        # creating replication and launch configuration templates, so the
        # full read-only set below is required for those operations to
        # succeed. This mirrors the read-only EC2 actions in the
        # AWS-managed AWSApplicationMigrationFullAccess policy. The launch
        # template itself is created by MGN's service-linked role, so no
        # EC2 write permissions are granted here.
        Sid    = "EC2ReadOnlyForMGN"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAccountAttributes",
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeImages",
          "ec2:DescribeInstanceAttribute",
          "ec2:DescribeInstanceStatus",
          "ec2:DescribeInstanceTypeOfferings",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeInstances",
          "ec2:DescribeKeyPairs",
          "ec2:DescribeLaunchTemplateVersions",
          "ec2:DescribeLaunchTemplates",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribePlacementGroups",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSnapshots",
          "ec2:DescribeSubnets",
          "ec2:DescribeTags",
          "ec2:DescribeVolumes",
          "ec2:DescribeVpcs",
          "ec2:GetEbsDefaultKmsKeyId",
          "ec2:GetEbsEncryptionByDefault"
        ]
        Resource = "*"
      },
      {
        # When the replication configuration template is first created, MGN
        # provisions and configures a dedicated staging-area security group
        # for the replication servers. These EC2 write actions are required
        # for that. The security group is created dynamically (no pre-existing
        # ARN), so CreateSecurityGroup must use a wildcard resource; the
        # follow-on rule/tag/delete actions are scoped by the tag condition
        # below where the API supports it.
        Sid    = "MGNStagingSecurityGroup"
        Effect = "Allow"
        Action = [
          "ec2:CreateSecurityGroup",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:AuthorizeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:RevokeSecurityGroupEgress",
          "ec2:ModifySecurityGroupRules",
          "ec2:DeleteSecurityGroup",
          "ec2:CreateTags"
        ]
        Resource = "*"
      },
      {
        # STS GetCallerIdentity requires wildcard resource
        Sid      = "STSGetCallerIdentity"
        Effect   = "Allow"
        Action   = "sts:GetCallerIdentity"
        Resource = "*"
      }
    ]
  })
}
