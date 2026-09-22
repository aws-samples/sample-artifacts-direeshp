# Lambda Function Outputs
output "lambda_function_arn" {
  description = "ARN of the MGN initializer Lambda function"
  value       = aws_lambda_function.mgn_initializer.arn
}

output "lambda_function_name" {
  description = "Name of the MGN initializer Lambda function"
  value       = aws_lambda_function.mgn_initializer.function_name
}

output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_role.arn
}

# Invocation Result
output "mgn_initialization_result" {
  description = "Result of MGN initialization"
  value = try(
    jsondecode(aws_lambda_invocation.initialize_mgn.result),
    { error = "Failed to parse Lambda response" }
  )
}
