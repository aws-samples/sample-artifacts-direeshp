# AWS Region
variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

# ---------------------------------------------------------------------------
# Multi-account provider configuration (all optional)
# ---------------------------------------------------------------------------

variable "aws_profile" {
  description = "Named AWS profile (from ~/.aws/config) to use for the target account. Leave empty to use the default credential chain."
  type        = string
  default     = ""
}

variable "assume_role_arn" {
  description = "ARN of an IAM role to assume in the target account for cross-account deployment. Leave empty to deploy into the credentials' own account."
  type        = string
  default     = ""
}

variable "assume_role_session_name" {
  description = "Session name used when assuming assume_role_arn"
  type        = string
  default     = "mgn-terraform"
}

variable "assume_role_external_id" {
  description = "External ID for the assume-role trust, if the target role requires one. Leave empty if not used."
  type        = string
  default     = ""
}

variable "default_tags" {
  description = "Tags applied to all resources created by this configuration"
  type        = map(string)
  default = {
    ManagedBy = "terraform"
    Project   = "mgn-initializer"
  }
}

# Lambda Configuration
variable "lambda_function_name" {
  description = "Name of the Lambda function"
  type        = string
  default     = "mgn-initializer"
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 900
}

variable "lambda_memory_size" {
  description = "Lambda function memory size in MB"
  type        = number
  default     = 256
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 14
}

# VPC Configuration (auto-discover if empty)
variable "staging_subnet_id" {
  description = "Subnet ID for MGN staging area. Leave empty to auto-discover default VPC subnet"
  type        = string
  default     = ""
}

variable "security_group_ids" {
  description = "Security group IDs for replication servers. Leave empty to auto-discover default SG"
  type        = list(string)
  default     = []
}

# Replication Configuration
variable "replication_instance_type" {
  description = "Instance type for MGN replication servers"
  type        = string
  default     = "t3.small"
}

variable "staging_disk_type" {
  description = "EBS disk type for staging area (GP2, GP3, ST1, etc.)"
  type        = string
  default     = "GP3"
}

variable "bandwidth_throttling" {
  description = "Bandwidth throttling in Mbps (0 = unlimited)"
  type        = number
  default     = 0
}

variable "create_public_ip" {
  description = "Create public IP for replication servers"
  type        = bool
  default     = false
}

variable "use_dedicated_replication_server" {
  description = "Use dedicated replication server"
  type        = bool
  default     = false
}

variable "data_plane_routing" {
  description = "Data plane routing (PRIVATE_IP or PUBLIC_IP)"
  type        = string
  default     = "PRIVATE_IP"
}

variable "associate_default_security_group" {
  description = "Associate default security group with replication servers"
  type        = bool
  default     = true
}

# KMS Configuration
variable "kms_key_arn" {
  description = "KMS key ARN for EBS encryption. Leave empty to use AWS managed key"
  type        = string
  default     = ""
}

# Launch Configuration
variable "copy_private_ip" {
  description = "Copy private IP to launched instances"
  type        = bool
  default     = false
}

variable "copy_tags" {
  description = "Copy tags to launched instances"
  type        = bool
  default     = true
}

variable "launch_disposition" {
  description = "Launch disposition (STARTED or STOPPED)"
  type        = string
  default     = "STARTED"
}

variable "target_instance_type_right_sizing" {
  description = "Target instance type right sizing method (NONE or BASIC)"
  type        = string
  default     = "BASIC"
}

variable "os_byol" {
  description = "Use Bring Your Own License for OS"
  type        = bool
  default     = false
}

# Post-Launch Actions
variable "post_launch_deployment" {
  description = "Post-launch actions deployment mode (TEST_AND_CUTOVER, CUTOVER_ONLY, TEST_ONLY)"
  type        = string
  default     = "TEST_AND_CUTOVER"
}

variable "cloudwatch_log_group_name" {
  description = "CloudWatch log group name for post-launch actions"
  type        = string
  default     = "/aws/mgn/post-launch-actions"
}

# SSM Agent Installation
variable "ssm_agent_must_succeed" {
  description = "SSM agent installation must succeed for cutover"
  type        = bool
  default     = true
}

# Staging Area Tags
variable "staging_area_tags" {
  description = "Tags to apply to staging area resources"
  type        = map(string)
  default = {
    Environment = "MGN"
    Service     = "Replication"
  }
}
