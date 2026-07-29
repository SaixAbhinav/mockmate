# AWS provider configuration (ADR 0029).

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      ADR       = "0029"
    }
  }
}
