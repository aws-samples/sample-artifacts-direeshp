# Region-scoped names so the template can be deployed to multiple regions
# in the same account. IAM roles are global, so the execution role name must
# include the region to avoid EntityAlreadyExists collisions across regions.
locals {
  function_name = "${var.lambda_function_name}-${var.aws_region}"
  role_name     = "${var.lambda_function_name}-role-${var.aws_region}"
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
}

# Lambda Function
resource "aws_lambda_function" "mgn_initializer" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = local.function_name
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.14"
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory_size
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  depends_on = [
    aws_cloudwatch_log_group.lambda_logs,
    aws_iam_role_policy.lambda_policy
  ]
}

# Invoke Lambda after creation
resource "aws_lambda_invocation" "initialize_mgn" {
  function_name = aws_lambda_function.mgn_initializer.function_name

  input = jsonencode({
    stagingAreaSubnetId                 = var.staging_subnet_id
    replicationServersSecurityGroupsIDs = var.security_group_ids
    replicationServerInstanceType       = var.replication_instance_type
    defaultLargeStagingDiskType         = var.staging_disk_type
    bandwidthThrottling                 = var.bandwidth_throttling
    createPublicIP                      = var.create_public_ip
    useDedicatedReplicationServer       = var.use_dedicated_replication_server
    dataPlaneRouting                    = var.data_plane_routing
    associateDefaultSecurityGroup       = var.associate_default_security_group
    kmsKeyArn                           = var.kms_key_arn
    copyPrivateIp                       = var.copy_private_ip
    copyTags                            = var.copy_tags
    launchDisposition                   = var.launch_disposition
    targetInstanceTypeRightSizingMethod = var.target_instance_type_right_sizing
    osByol                              = var.os_byol
    postLaunchDeployment                = var.post_launch_deployment
    cloudWatchLogGroupName              = var.cloudwatch_log_group_name
    ssmAgentMustSucceed                 = var.ssm_agent_must_succeed
    stagingAreaTags                     = var.staging_area_tags
  })

  triggers = {
    redeployment = sha256(jsonencode({
      source_hash = data.archive_file.lambda_zip.output_base64sha256
    }))
  }

  depends_on = [aws_lambda_function.mgn_initializer]
}

# Write initialization result to file
resource "local_file" "mgn_init_output" {
  content = jsonencode(
    try(
      jsondecode(aws_lambda_invocation.initialize_mgn.result),
      { error = "Failed to parse Lambda response" }
    )
  )
  filename = "${path.module}/mgn-init-output-${var.aws_region}.json"
}
