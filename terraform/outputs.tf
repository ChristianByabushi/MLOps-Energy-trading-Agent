# terraform/outputs.tf
# Output values for the MLOps Energy Trading Agent infrastructure

output "trading_logs_bucket_name" {
  description = "Name of the S3 bucket for trading decision logs"
  value       = aws_s3_bucket.trading_logs.bucket
}

output "trading_logs_bucket_arn" {
  description = "ARN of the S3 bucket for trading decision logs"
  value       = aws_s3_bucket.trading_logs.arn
}

output "terraform_state_bucket_name" {
  description = "Name of the S3 bucket for Terraform remote state"
  value       = aws_s3_bucket.terraform_state.bucket
}

output "terraform_state_lock_table_name" {
  description = "Name of the DynamoDB table for Terraform state locking"
  value       = aws_dynamodb_table.terraform_locks.name
}

output "lambda_execution_role_arn" {
  description = "ARN of the IAM execution role for the Lambda function"
  value       = aws_iam_role.lambda_execution.arn
}

output "lambda_execution_role_name" {
  description = "Name of the IAM execution role for the Lambda function"
  value       = aws_iam_role.lambda_execution.name
}
