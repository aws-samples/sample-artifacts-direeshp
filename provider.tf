provider "aws" {
  region = var.aws_region

  # Multi-account support (all optional — empty values keep the default
  # single-account behavior using the ambient credential chain).
  #
  # Option 1: use a named profile from ~/.aws/config for the target account.
  profile = var.aws_profile != "" ? var.aws_profile : null

  # Option 2: assume a role in the target account (cross-account deploy).
  # Set assume_role_arn to a role ARN in the account you want to deploy to.
  dynamic "assume_role" {
    for_each = var.assume_role_arn != "" ? [1] : []
    content {
      role_arn     = var.assume_role_arn
      session_name = var.assume_role_session_name
      external_id  = var.assume_role_external_id != "" ? var.assume_role_external_id : null
    }
  }

  # Tag everything so resources are traceable per account/deployment.
  default_tags {
    tags = var.default_tags
  }
}

# Terraform backend configuration
# Option 1: S3 backend (default)
# terraform {
#   backend "s3" {
#     bucket       = "my-terraform-state-bucket"
#     key          = "path/to/my/terraform.tfstate"
#     region       = "us-east-1"
#     encrypt      = true
#     use_lockfile = true
#   }
# }

# Option 2: Terraform Cloud/Enterprise (alternative)
# Delete the backend "s3" block above and uncomment the cloud block below
# to use Terraform Cloud/Enterprise
# terraform {
#   cloud {}
# }

# Note: You can only have one backend configuration active at a time.
