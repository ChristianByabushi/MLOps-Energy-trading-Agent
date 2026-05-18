"""Quick S3 connectivity test — verifies credentials and bucket access."""
import os
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

import boto3
from botocore.exceptions import NoCredentialsError, ClientError

bucket = os.environ.get("S3_BUCKET_NAME", "")
region = os.environ.get("AWS_REGION", "eu-central-1")
key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

print(f"Bucket : {bucket}")
print(f"Region : {region}")
print(f"Key ID : {key_id[:8]}...{key_id[-4:] if len(key_id) > 12 else '(not set)'}")
print()

# Build client — use explicit keys if set, otherwise fall back to ~/.aws/credentials
kwargs = {"region_name": region}
if key_id and secret:
    kwargs["aws_access_key_id"]     = key_id
    kwargs["aws_secret_access_key"] = secret

s3 = boto3.client("s3", **kwargs)

# Test 1: credentials work
print("Test 1: AWS credentials ...")
try:
    s3.list_buckets()
    print("  ✅ Credentials valid")
except NoCredentialsError:
    print("  ❌ No credentials found.")
    print("     Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env")
    raise SystemExit(1)
except ClientError as e:
    print(f"  ❌ {e}")
    raise SystemExit(1)

# Test 2: bucket exists and is writable
print(f"Test 2: Upload to s3://{bucket}/test/hello.json ...")
try:
    payload = json.dumps({"test": True, "ts": datetime.utcnow().isoformat()})
    s3.put_object(
        Bucket=bucket,
        Key="test/hello.json",
        Body=payload.encode("utf-8"),
        ContentType="application/json",
    )
    print("  ✅ Upload OK")
except ClientError as e:
    code = e.response["Error"]["Code"]
    print(f"  ❌ {code}: {e}")
    if code == "NoSuchBucket":
        print(f"     Bucket '{bucket}' does not exist in region '{region}'.")
        print(f"     Create it with:  aws s3 mb s3://{bucket} --region {region}")
    elif code in ("AccessDenied", "403"):
        print(f"     Your IAM user does not have s3:PutObject on this bucket.")
    raise SystemExit(1)

# Test 3: read it back
print(f"Test 3: Read back test/hello.json ...")
try:
    obj = s3.get_object(Bucket=bucket, Key="test/hello.json")
    content = obj["Body"].read().decode("utf-8")
    print(f"  ✅ Read OK: {content}")
except ClientError as e:
    print(f"  ❌ {e}")
    raise SystemExit(1)

print()
print("All S3 tests passed. The agent will upload decisions to:")
print(f"  s3://{bucket}/logs/YYYY-MM-DD/{{uuid}}.json")
