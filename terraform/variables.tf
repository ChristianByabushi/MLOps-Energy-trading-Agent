# terraform/variables.tf
# Input variables for the MLOps Energy Trading Agent infrastructure

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-central-1"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "trading_logs_bucket_name" {
  description = "Name of the S3 bucket for trading decision logs"
  type        = string
  default     = "energy-trading-logs"
}

variable "terraform_state_bucket_name" {
  description = "Name of the S3 bucket for Terraform remote state"
  type        = string
  default     = "energy-trading-terraform-state"
}

variable "terraform_state_lock_table" {
  description = "Name of the DynamoDB table for Terraform state locking"
  type        = string
  default     = "energy-trading-terraform-locks"
}

variable "lambda_function_name" {
  description = "Name of the Lambda function"
  type        = string
  default     = "energy-trading-agent"
}

variable "lambda_execution_role_name" {
  description = "Name of the IAM execution role for the Lambda function"
  type        = string
  default     = "energy-trading-agent-lambda-role"
}
