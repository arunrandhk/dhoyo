#!/usr/bin/env bash
# Runs on each managed EC2 node. Secret values never leave this node in output.
set +x
set -euo pipefail
umask 077

image=${1:?Missing deployment image}
region=${2:?Missing AWS region}
secret_name=${3:?Missing Secrets Manager secret name}
registry=${image%%/*}

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
secret_file="$work_dir/secret.json"
env_file="$work_dir/container.env"
docker_config="$work_dir/docker"
mkdir "$docker_config"

# Fetch on EC2 using its instance role, rather than putting values in the SSM
# document, GitHub logs, shell command arguments or Docker command arguments.
aws secretsmanager get-secret-value \
  --secret-id "$secret_name" --region "$region" \
  --query SecretString --output text --no-cli-pager > "$secret_file"

python3 - "$secret_file" "$env_file" <<'BYTE_SECRET_ENV'
import json
import os
from pathlib import Path
import sys

try:
    secret = json.loads(Path(sys.argv[1]).read_text())
except (OSError, UnicodeError, ValueError):
    raise SystemExit('Deployment stopped: Secrets Manager must contain a valid JSON object.')
if not isinstance(secret, dict):
    raise SystemExit('Deployment stopped: Secrets Manager must contain a valid JSON object.')

fields = {
    'DB_HOST': 'host', 'DB_PORT': 'port', 'DB_NAME': 'dbname',
    'DB_USER': 'username', 'DB_PASSWORD': 'password',
    'AUTH_JWT_SECRET': 'auth_jwt_secret'
}
values = {}
for environment_name, secret_name in fields.items():
    value = secret.get(secret_name)
    if environment_name == 'DB_PORT' and isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value or any(character in value for character in '\r\n\x00'):
        raise SystemExit(f'Deployment stopped: invalid or missing {secret_name} in Secrets Manager.')
    values[environment_name] = value

if not values['DB_PORT'].isdigit() or not 1 <= int(values['DB_PORT']) <= 65535:
    raise SystemExit('Deployment stopped: invalid port in Secrets Manager.')
try:
    valid_key = len(values['AUTH_JWT_SECRET'].encode('utf-8')) >= 32
except UnicodeError:
    valid_key = False
if not valid_key:
    raise SystemExit('Deployment stopped: auth_jwt_secret must contain at least 32 UTF-8 bytes.')

# Docker env files are literal KEY=VALUE lines, not shell scripts. Quotes and
# command substitutions in passwords stay literal; line breaks are rejected.
with open(sys.argv[2], 'x', encoding='utf-8') as output:
    for name, value in values.items():
        output.write(f'{name}={value}\n')
os.chmod(sys.argv[2], 0o600)
BYTE_SECRET_ENV

# Validate the secret and acquire the image before interrupting the old app.
aws ecr get-login-password --region "$region" --no-cli-pager \
  | docker --config "$docker_config" login --username AWS --password-stdin "$registry" > /dev/null
docker --config "$docker_config" pull "$image" > /dev/null

if docker inspect --type container byte-app > /dev/null 2>&1; then
  docker stop byte-app > /dev/null
  docker rm byte-app > /dev/null
fi
docker run -d --name byte-app --restart unless-stopped \
  -p 8080:8080 --env-file "$env_file" "$image" > /dev/null

curl --fail --silent --show-error --retry 10 --retry-connrefused \
  --retry-delay 2 --max-time 5 http://127.0.0.1:8080/health > /dev/null
echo 'Deployment completed and the local health check passed.'
