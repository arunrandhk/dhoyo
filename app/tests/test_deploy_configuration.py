"""Deployment carries optional identity/mail settings as literal private values."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def prepare(tmp_path, **optional):
    script = (Path(__file__).resolve().parents[2] / 'scripts/deploy_ec2.sh').read_text()
    program = script.split("<<'BYTE_SECRET_ENV'\n", 1)[1].split('\nBYTE_SECRET_ENV', 1)[0]
    settings = dict(host='localhost', port=5432, dbname='test-db', username='test-user',
                    password='synthetic-db-password', auth_jwt_secret='synthetic-deploy-key-' + 'a' * 32,
                    **optional)
    secret_file, output_file = tmp_path / 'secret.json', tmp_path / 'container.env'
    secret_file.write_text(json.dumps(settings))
    result = subprocess.run([sys.executable, '-c', program, str(secret_file), str(output_file)],
                            capture_output=True, text=True, timeout=10)
    return result, output_file


def test_optional_google_and_mail_values_reach_private_environment_without_shell_expansion(tmp_path):
    password = 'synthetic-$(not-a-command)-`literal`-"quoted"'
    result, output = prepare(tmp_path, google_client_id='test.apps.googleusercontent.com',
                             password_reset_base_url='https://dhoyo.example/ring', smtp_host='mail.example',
                             smtp_port=587, smtp_password=password, smtp_use_tls=True)
    assert result.returncode == 0, result.stderr
    values = dict(line.split('=', 1) for line in output.read_text().splitlines())
    assert values['GOOGLE_CLIENT_ID'] == 'test.apps.googleusercontent.com'
    assert values['PASSWORD_RESET_BASE_URL'] == 'https://dhoyo.example/ring'
    assert values['SMTP_PORT'] == '587' and values['SMTP_USE_TLS'] == 'true'
    assert values['SMTP_PASSWORD'] == password
    assert output.stat().st_mode & 0o777 == 0o600
    assert result.stdout == '' and result.stderr == ''


def test_play_games_secrets_stay_private_and_are_forwarded_literally(tmp_path):
    result, output = prepare(tmp_path, play_games_application_id='123456789',
                             play_games_web_client_secret='synthetic-private-game-secret',
                             play_games_achievements_json='{"first-team":"CgkExample"}',
                             android_package_name='com.dhoyo.app')
    assert result.returncode == 0, result.stderr
    values = dict(line.split('=', 1) for line in output.read_text().splitlines())
    assert values['PLAY_GAMES_APPLICATION_ID'] == '123456789'
    assert values['PLAY_GAMES_WEB_CLIENT_SECRET'] == 'synthetic-private-game-secret'
    assert values['PLAY_GAMES_ACHIEVEMENTS_JSON'] == '{"first-team":"CgkExample"}'
    assert values['ANDROID_PACKAGE_NAME'] == 'com.dhoyo.app'
    assert not result.stdout and not result.stderr


@pytest.mark.parametrize('value', ['synthetic\nINJECTED=value', 'synthetic\rvalue', 'synthetic\x00value', 123, True])
def test_invalid_optional_provider_values_cannot_inject_environment_entries_or_logs(tmp_path, value):
    result, output = prepare(tmp_path, resend_api_key=value)
    assert result.returncode != 0
    assert not output.exists()
    assert 'invalid resend_api_key' in result.stderr
    assert 'synthetic' not in result.stdout + result.stderr


def test_existing_database_only_secret_keeps_optional_integrations_disabled(tmp_path):
    result, output = prepare(tmp_path)
    assert result.returncode == 0
    assert 'GOOGLE_CLIENT_ID' not in output.read_text()
    assert 'RESEND_API_KEY' not in output.read_text()
