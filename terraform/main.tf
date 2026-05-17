# terraform/main.tf
# Infrastructure for the MLOps Energy Trading Agent
#
# Provisions:
# - S3 bucket for trading decision logs
# - S3 bucket for Terraform remote state (with versioning)
# - DynamoDB table for Terraform state locking
# - IAM execution role for Lambda with least-privilege S3 access

terraform {
  required_version = ">= 1.8"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state backend — stores Terraform state in S3 with DynamoDB locking.
  # NOTE: The state bucket and DynamoDB table must be created manually (or via
  # a bootstrap script) before running `terraform init` for the first time.
  # Uncomment and configure this block after bootstrapping:
  #
  # backend "s3" {
  #   bucket         = "energy-trading-terraform-state"
  #   key            = "energy-trading-agent/terraform.tfstate"
  #   region         = "eu-central-1"
  #   dynamodb_table = "energy-trading-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "mlops-energy-trading-agent"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ---------------------------------------------------------------------------
# S3 Bucket: Trading Decision Logs
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "trading_logs" {
  bucket = "${var.trading_logs_bucket_name}-${var.environment}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "trading_logs" {
  bucket = aws_s3_bucket.trading_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "trading_logs" {
  bucket = aws_s3_bucket.trading_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "trading_logs" {
  bucket = aws_s3_bucket.trading_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# S3 Bucket: Terraform Remote State
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "terraform_state" {
  bucket = "${var.terraform_state_bucket_name}-${var.environment}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# DynamoDB Table: Terraform State Locking
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "terraform_locks" {
  name         = "${var.terraform_state_lock_table}-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

# ---------------------------------------------------------------------------
# IAM: Lambda Execution Role with Least-Privilege S3 Access
# ---------------------------------------------------------------------------

# Trust policy: only Lambda service can assume this role
data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_execution" {
  name               = "${var.lambda_execution_role_name}-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  description = "IAM execution role for the energy trading agent Lambda function"
}

# Least-privilege policy: only s3:PutObject on the trading-logs bucket
data "aws_iam_policy_document" "lambda_s3_policy" {
  statement {
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.trading_logs.arn}/logs/*"]
  }
}

resource "aws_iam_policy" "lambda_s3_write" {
  name        = "energy-trading-agent-s3-write-${var.environment}"
  description = "Allows Lambda to write trading decision logs to S3"
  policy      = data.aws_iam_policy_document.lambda_s3_policy.json
}

resource "aws_iam_role_policy_attachment" "lambda_s3_write" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = aws_iam_policy.lambda_s3_write.arn
}

# Attach AWS managed policy for basic Lambda execution (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
