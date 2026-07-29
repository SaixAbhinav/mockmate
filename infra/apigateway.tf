# API Gateway HTTP API in front of the Lambda function (ADR 0029, PR 2b).
# One catch-all AWS_PROXY integration - the FastAPI app (backend/app/main.py)
# owns all routing under /api/*, so API Gateway just needs to forward
# everything to the Lambda and let uvicorn/FastAPI (via the Web Adapter)
# handle it, rather than modeling each route here.

resource "aws_apigatewayv2_api" "http" {
  name          = "mockmate-backend"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id = aws_apigatewayv2_api.http.id

  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.backend.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"

  # NOTE: API Gateway HTTP API integration timeouts cap at 30s regardless of
  # what's set here; the Lambda's own 60s timeout (lambda.tf) is what
  # actually matters for letting an Evaluation finish and cache - see that
  # resource's comment (ADR 0029 "Race A").
}

# Catches every path under the app's /api prefix (and anything else the app
# might serve, e.g. /docs) - the app itself 404s on paths it doesn't own.
resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# {proxy+} alone does not match the bare root path ("/"), only "/something" -
# add it explicitly so a request to "/" also reaches the Lambda.
resource "aws_apigatewayv2_route" "root" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
}

# Grants API Gateway permission to invoke the function. source_arn is scoped
# to this API's execution ARN (every stage/route/method on it), not to "any
# API Gateway in the account".
resource "aws_lambda_permission" "apigateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.backend.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
