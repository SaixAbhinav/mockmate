# The app's session/evaluation table (ADR 0029).
#
# Name and key schema are hard-wired to match `DynamoDBSessionStore` in
# backend/app/session_store.py exactly: table name "mockmate" (the
# MOCKMATE_DDB_TABLE env var's default), partition key `pk` (session_id,
# string), sort key `sk` ("session" | "eval", string). Sessions and their
# Evaluations share a partition, distinguished by sort key - see that
# module's docstring for why. Do not rename without updating the store.

resource "aws_dynamodb_table" "sessions" {
  name         = "mockmate"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = "mockmate"
  }
}
