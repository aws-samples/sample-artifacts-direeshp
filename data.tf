# Data sources
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Archive Lambda function
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/Lambda/lambda_function.py"
  output_path = "${path.module}/builds/mgn-initializer.zip"
}
