# Container registry for the backend image (ADR 0029). PR 2b's Lambda
# function is built from an image pushed here; this repo just needs to
# exist first so image builds/pushes and the Lambda function are
# independent steps.

resource "aws_ecr_repository" "backend" {
  name                 = "mockmate"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "mockmate"
  }
}

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after ${var.ecr_untagged_image_expiry_days} days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.ecr_untagged_image_expiry_days
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
