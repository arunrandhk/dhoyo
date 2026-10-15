"""Exercise the files shipped by Docker without requiring a local Docker daemon."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import textwrap

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def copy_container_sources(dockerfile, runtime):
    """Recreate the Dockerfile's local COPY inputs in an isolated work directory."""
    for line in dockerfile.read_text().splitlines():
        if not line.strip().startswith('COPY '):
            continue
        tokens = shlex.split(line)
        sources, destination = tokens[1:-1], tokens[-1]
        assert sources and not any(source.startswith('--') for source in sources)
        target = runtime / destination.lstrip('/')
        for source_name in sources:
            source = dockerfile.parent / source_name
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target / source.name)


def test_packaged_application_starts_and_serves_account_features(tmp_path):
    runtime = tmp_path / 'container-app'
    runtime.mkdir()
    dockerfile = Path(__file__).resolve().parents[1] / 'Dockerfile'
    copy_container_sources(dockerfile, runtime)
    environment = dict(os.environ, SPORTSPACE_SOCIAL_DB=str(tmp_path / 'container-state.sqlite'),
                       AUTH_ALLOW_INSECURE_LOCAL='1')
    script = textwrap.dedent('''
        import os
        import sys
        from datetime import datetime, timedelta, timezone
        sys.path.insert(0, os.getcwd())
        from app import app

        app.config['AUTH_TEST_DEMO'] = False
        # Domain smoke checks use the same explicit plaintext fixture opt-in as
        # the API tests; credential encryption has its own strict regression suite.
        app.config.update(TESTING=True, AUTH_TEST_ALLOW_PLAINTEXT=True, AUTH_TEST_LEGACY_REGISTRATION=True)
        headers = {'X-Dhoyo-Request': '1'}
        owner, peer = app.test_client(), app.test_client()
        assert owner.get('/health').status_code == 200
        assert owner.get('/api/friends').status_code == 401

        def register(client, name, **options):
            response = client.post('/api/auth/register', headers=headers, json=dict(
                name=name, email=name.lower() + '@example.com', password='container-test-password',
                sport='Football', city='Delhi', state='Delhi', country='India', **options))
            assert response.status_code == 201, response.get_data(as_text=True)
            return response.json['userId']

        owner_id, peer_id = register(owner, 'Owner'), register(peer, 'Peer')
        assert peer.get('/api/tournaments').status_code == 200

        organiser = app.test_client()
        register(organiser, 'Organiser', accountType='organisation', organisationName='Test Sports')
        starts = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
        response = organiser.post('/api/tournaments', headers=headers, json=dict(
            name='Packaged Cup', sport='Football', eventType='online',
            startsAt=starts.isoformat(), timezone='UTC', durationHours=2,
            registrationClosesAt=(starts - timedelta(hours=1)).isoformat(), capacity=2,
            teamSize=1, playerEmailConfirmation='activation_link', publish=True))
        assert response.status_code == 201, response.get_data(as_text=True)
        registration_url = '/api/tournaments/' + response.json['tournament']['id'] + '/registrations'
        response = owner.post(registration_url, headers=headers, json=dict(
            teamName='First Team', playerEmails=[dict(email='peer@example.com')]))
        assert response.status_code == 201, response.get_data(as_text=True)
        assert peer.get('/api/tournaments').json['tournaments'][0]['isParticipant'] is True
        response = peer.post(registration_url, headers=headers, json=dict(teamName='Second Team'))
        assert response.status_code == 409, response.get_data(as_text=True)

        assert owner.get('/api/friends').json['friends'] == []
        assert any(player['id'] == peer_id for player in owner.get('/api/friends/players').json['players'])
        response = owner.patch('/api/arena/players/' + owner_id,
                               headers=headers, json={'photoPrivacy': 'friends'})
        assert response.status_code == 200, response.get_data(as_text=True)
        profile = peer.get('/api/arena/players/' + owner_id).json['player']
        assert profile['photoPrivacy'] == 'friends' and profile['canViewPhotos'] is False

        response = peer.post('/api/friends/requests', headers=headers, json={'playerId': owner_id})
        assert response.status_code == 201, response.get_data(as_text=True)
        request_id = response.json['request']['id']
        assert owner.get('/api/friends').json['incomingCount'] == 1
        response = owner.post('/api/friends/requests/' + request_id,
                              headers=headers, json={'action': 'accept'})
        assert response.status_code == 200, response.get_data(as_text=True)
        assert peer.get('/api/arena/players/' + owner_id).json['player']['canViewPhotos'] is True

        # This send also loads the sticker catalog from the packaged static tree.
        response = owner.post('/api/messages/conversations/' + peer_id,
                              headers=headers, json={'stickerId': 'gg'})
        assert response.status_code == 201, response.get_data(as_text=True)
        assert peer.get('/api/messages/conversations/' + owner_id).json['messages'][0]['stickerId'] == 'gg'

        # Invalid input exercises recovery registration without sending any email.
        response = owner.post('/api/auth/request-password-code', headers=headers, json={})
        assert response.status_code == 400 and 'email' in response.json['error'].lower()
        for path in ('/static/sportspace/friends.js', '/static/sportspace/account-security.js',
                     '/static/sportspace/organisations.js'):
            response = owner.get(path)
            assert response.status_code == 200 and len(response.data) > 100, path
        print('Packaged application startup and account features passed')
    ''')
    result = subprocess.run([sys.executable, '-I', '-c', script], cwd=runtime,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Packaged application startup and account features passed' in result.stdout
