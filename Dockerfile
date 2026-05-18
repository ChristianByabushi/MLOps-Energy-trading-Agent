# Use the official AWS Lambda Python 3.12 base image
FROM public.ecr.aws/lambda/python:3.12

# Set working directory to Lambda task root
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy dependency specification first (for layer caching)
COPY pyproject.toml ./

# Install only production dependencies (no dev/test extras)
# We install the package itself in non-editable mode to avoid needing setuptools at runtime
RUN pip install --no-cache-dir \
    "pydantic-ai>=0.0.14" \
    "pydantic>=2.7" \
    "pydantic-settings>=2.3" \
    "boto3>=1.34" \
    "httpx>=0.27" \
    "python-dotenv>=1.0" \
    "urllib3>=2.7.0"

# Copy application source code
COPY agent/ ./agent/
COPY lambda_handler.py ./
COPY data/ ./data/

# Lambda handler entry point
# Format: <module_name>.<function_name>
CMD ["lambda_handler.handler"]
