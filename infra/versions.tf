# Terraform + provider version pins, and the remote state backend (ADR 0029).
#
# The S3 bucket and DynamoDB lock table referenced below are bootstrapped
# OUT of Terraform (standard chicken-and-egg: Terraform cannot create the
# backend it is about to start using). See infra/README.md for how they
# were created. `dynamodb_table` is deprecated in newer Terraform versions
# in favor of `use_lockfile`, but the lock table already exists and this
# stays on the widely-supported form.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "mockmate-tfstate-356252962813"
    key            = "mockmate/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "mockmate-tflock"
    encrypt        = true
  }
}
