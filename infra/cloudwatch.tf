# CloudWatch monitoring (ADR 0029, PR 5): one alerts topic, one dashboard,
# and a handful of alarms covering Lambda, API Gateway, and DynamoDB. Kept
# deliberately inside the free tier named in ADR 0029's cost table -
# **1 dashboard** (3 free) and **5 alarms** (10 free) - see infra/README.md's
# Monitoring section for what each one means and how to subscribe to it.
#
# No email subscription is created here on purpose: `aws_sns_topic_subscription`
# with protocol "email" sits PENDING until a human clicks the confirmation link
# AWS emails them, so it can't be a clean `apply`-able resource. infra/README.md
# documents the one-line `aws sns subscribe` instead.

resource "aws_sns_topic" "alerts" {
  name = "mockmate-alerts"

  tags = {
    Name = "mockmate-alerts"
  }
}

# One dashboard, four rows (Lambda / API Gateway / DynamoDB / CloudFront),
# two widgets per row. All four resources already exist elsewhere in infra/ -
# every id below is a resource attribute reference, never a hard-coded id.
resource "aws_cloudwatch_dashboard" "mockmate" {
  dashboard_name = "mockmate"

  dashboard_body = jsonencode({
    widgets = [
      # Row 1 - Lambda
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Lambda - Invocations / Errors / Throttles"
          region = var.region
          period = 300
          stat   = "Sum"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.backend.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.backend.function_name],
            ["AWS/Lambda", "Throttles", "FunctionName", aws_lambda_function.backend.function_name],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Lambda - Duration (avg / p99)"
          region = var.region
          period = 300
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.backend.function_name, { stat = "Average", label = "Duration (avg)" }],
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.backend.function_name, { stat = "p99", label = "Duration (p99)" }],
          ]
        }
      },

      # Row 2 - API Gateway (HTTP API metric names are lowercase "4xx"/"5xx",
      # unlike the REST-API "4XXError"/"5XXError" - verified against AWS's
      # HTTP API metrics docs, not assumed from the REST API naming).
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "API Gateway - Count / 4xx / 5xx"
          region = var.region
          period = 300
          stat   = "Sum"
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", aws_apigatewayv2_api.http.id],
            ["AWS/ApiGateway", "4xx", "ApiId", aws_apigatewayv2_api.http.id],
            ["AWS/ApiGateway", "5xx", "ApiId", aws_apigatewayv2_api.http.id],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "API Gateway - Latency (avg)"
          region = var.region
          period = 300
          stat   = "Average"
          metrics = [
            ["AWS/ApiGateway", "Latency", "ApiId", aws_apigatewayv2_api.http.id],
          ]
        }
      },

      # Row 3 - DynamoDB
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "DynamoDB - Consumed Capacity"
          region = var.region
          period = 300
          stat   = "Sum"
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", aws_dynamodb_table.sessions.name],
            ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", aws_dynamodb_table.sessions.name],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "DynamoDB - Throttle Events"
          region = var.region
          period = 300
          stat   = "Sum"
          metrics = [
            ["AWS/DynamoDB", "ReadThrottleEvents", "TableName", aws_dynamodb_table.sessions.name],
            ["AWS/DynamoDB", "WriteThrottleEvents", "TableName", aws_dynamodb_table.sessions.name],
          ]
        }
      },

      # Row 4 - CloudFront. CloudFront metrics are only ever published to
      # us-east-1 regardless of the distribution's own scope (it's a global
      # service) - this "region" is hard-coded to that AWS constraint, not
      # to var.region (the two happen to match today, but for a different
      # reason; don't collapse them into one variable).
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 12
        height = 6
        properties = {
          title  = "CloudFront - Requests"
          region = "us-east-1"
          period = 300
          stat   = "Sum"
          metrics = [
            ["AWS/CloudFront", "Requests", "DistributionId", aws_cloudfront_distribution.frontend.id, "Region", "Global"],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 18
        width  = 12
        height = 6
        properties = {
          title  = "CloudFront - Error Rates (%)"
          region = "us-east-1"
          period = 300
          stat   = "Average"
          metrics = [
            ["AWS/CloudFront", "4xxErrorRate", "DistributionId", aws_cloudfront_distribution.frontend.id, "Region", "Global"],
            ["AWS/CloudFront", "5xxErrorRate", "DistributionId", aws_cloudfront_distribution.frontend.id, "Region", "Global"],
          ]
        }
      },
    ]
  })
}

# --- Alarms ------------------------------------------------------------
# Five alarms, each notifying the one SNS topic above on both ALARM and OK
# transitions. `treat_missing_data = "notBreaching"` throughout: a gap in
# data (e.g. zero invocations for a period) should never itself page anyone
# - only an actual error/throttle/latency/threshold breach should.

# 1. Lambda Errors - any error at all is worth a look; two consecutive 5-minute
# periods (not one) so a single blip that resolves itself doesn't page.
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "mockmate-lambda-errors"
  alarm_description   = "Backend Lambda (mockmate-backend) returned errors in two consecutive 5-minute periods."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.backend.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# 2. Lambda Throttles - concurrency limit was hit; same two-period pattern.
resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  alarm_name          = "mockmate-lambda-throttles"
  alarm_description   = "Backend Lambda (mockmate-backend) was throttled (concurrency limit) in two consecutive 5-minute periods."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = aws_lambda_function.backend.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# 3. Lambda Duration p99 approaching the 60s timeout (lambda.tf) - 55000ms
# gives a 5s margin, so this fires *before* requests start hard-timing-out
# rather than after (see lambda.tf's comment on the deliberate 60s timeout
# and "Race A"). Extended statistic, not the plain "Maximum"/"Average" -
# p99 catches a sustained tail without one single slow invocation tripping it.
resource "aws_cloudwatch_metric_alarm" "lambda_duration_p99" {
  alarm_name          = "mockmate-lambda-duration-p99"
  alarm_description   = "Backend Lambda (mockmate-backend) p99 duration is within 5s of the 60s function timeout."
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  dimensions          = { FunctionName = aws_lambda_function.backend.function_name }
  extended_statistic  = "p99"
  period              = 300
  evaluation_periods  = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = 55000 # milliseconds
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# 4. API Gateway 5xx - small threshold (not >0) because a lone 5xx can be a
# transient Lambda cold-start hiccup; more than 5 in a 5-minute window is a
# real signal something's actually broken.
resource "aws_cloudwatch_metric_alarm" "apigateway_5xx" {
  alarm_name          = "mockmate-apigateway-5xx"
  alarm_description   = "API Gateway (mockmate-backend HTTP API) returned more than 5 5xx responses in a 5-minute period."
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = aws_apigatewayv2_api.http.id }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# 5. DynamoDB throttles - a metric-math alarm summing Read+WriteThrottleEvents
# so one alarm covers both directions instead of two near-duplicate alarms
# (keeps the total alarm count down while still catching either kind).
resource "aws_cloudwatch_metric_alarm" "dynamodb_throttles" {
  alarm_name          = "mockmate-dynamodb-throttles"
  alarm_description   = "The mockmate DynamoDB table was throttled (read or write) at least once in a 5-minute period."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  metric_query {
    id          = "throttles"
    expression  = "reads + writes"
    label       = "Read + write throttle events"
    return_data = true
  }

  metric_query {
    id = "reads"
    metric {
      namespace   = "AWS/DynamoDB"
      metric_name = "ReadThrottleEvents"
      period      = 300
      stat        = "Sum"
      dimensions  = { TableName = aws_dynamodb_table.sessions.name }
    }
  }

  metric_query {
    id = "writes"
    metric {
      namespace   = "AWS/DynamoDB"
      metric_name = "WriteThrottleEvents"
      period      = 300
      stat        = "Sum"
      dimensions  = { TableName = aws_dynamodb_table.sessions.name }
    }
  }
}
