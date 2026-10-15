"""Package the EC2 deployment script as JSON without fetching any secrets."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex


def build_parameters(image, region, secret_name):
    if not isinstance(image, str) or not re.fullmatch(
        r"\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?/[-a-z0-9_./]+:[A-Za-z0-9_.-]+", image
    ):
        raise ValueError("Deployment requires a tagged ECR image")
    if not isinstance(region, str) or not re.fullmatch(r"[a-z0-9-]+", region):
        raise ValueError("Deployment requires an AWS region")
    if not isinstance(secret_name, str) or not re.fullmatch(r"[A-Za-z0-9/_+=.@:-]+", secret_name):
        raise ValueError("Deployment requires a Secrets Manager secret name or ARN")
    script = Path(__file__).with_name("deploy_ec2.sh").read_text()
    arguments = " ".join(shlex.quote(value) for value in (image, region, secret_name))
    command = f"bash -s -- {arguments} <<'BYTE_EC2_DEPLOY_SCRIPT'\n{script}\nBYTE_EC2_DEPLOY_SCRIPT"
    return {"commands": [command]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        parameters = build_parameters(os.environ.get("IMAGE"), os.environ.get("AWS_REGION"), os.environ.get("SECRET_NAME"))
    except ValueError as problem:
        parser.error(str(problem))
    arguments.output.write_text(json.dumps(parameters))


if __name__ == "__main__":
    main()
