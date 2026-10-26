"""Real account sessions enforce photo access across every API that shows media."""
import base64
from io import BytesIO
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app
from social import raw_state


HEADERS = {'X-Dhoyo-Request': '1'}


def mutate(client, method, path, payload):
    return getattr(client, method)(path, json=payload, headers=HEADERS)


def upload(color):
    output = BytesIO()
    Image.new('RGB', (48, 28), color).save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()


@pytest.fixture
def private_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'photos.sqlite'))
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    clients, ids = {}, {}
    for role in ('owner', 'friend', 'pending', 'stranger'):
        client = app.test_client()
        result = mutate(client, 'post', '/api/auth/register', dict(
            name=role.title(), email=role + '@example.com', password='long-photo-password',
            sport='Football', city='Delhi', state='Delhi', country='India'))
        assert result.status_code == 201
        clients[role], ids[role] = client, result.json['userId']
    owner = clients['owner']
    result = mutate(owner, 'patch', '/api/arena/players/' + ids['owner'], dict(
        avatar=upload('blue'), cover=upload('green')))
    assert result.status_code == 200
    photo = mutate(owner, 'post', '/api/social/posts', dict(
        text='Private photo caption', sport='Football',
        image='https://example.com/secret-owner-post-photo.jpg')).json
    text = mutate(owner, 'post', '/api/social/posts', dict(
        text='Public text from a private-photo account', sport='Football')).json
    story = mutate(owner, 'post', '/api/social/stories', dict(
        sport='Football', image='https://example.com/secret-owner-story-photo.jpg')).json
    profile = owner.get('/api/arena/players/' + ids['owner']).json['player']
    # Legacy discovery and community covers copy a profile image URI.
    with raw_state() as data:
        stored = next(p for p in data['arena']['players'] if p['id'] == ids['owner'])
        stored['image'] = photo['image']
        data['arena']['communities'][0]['image'] = photo['image']
        data['arena']['communities'][0]['memberIds'].append(ids['owner'])
    requests = {}
    for role in ('friend', 'pending'):
        response = mutate(clients[role], 'post', '/api/friends/requests', {'playerId': ids['owner']})
        assert response.status_code == 201
        requests[role] = response.json['request']['id']
    response = mutate(owner, 'post', '/api/friends/requests', {'playerId': ids['stranger']})
    requests['stranger'] = response.json['request']['id']
    # A conversation exposes the peer's avatar even before friendship.
    for role in ('friend', 'pending', 'stranger'):
        response = mutate(clients[role], 'post', '/api/messages/conversations/' + ids['owner'],
                          {'stickerId': 'gg'})
        assert response.status_code == 201
    return dict(clients=clients, ids=ids, requests=requests, photo=photo, text=text,
                story=story, secrets=[photo['image'], story['image'], profile['avatar'], profile['cover']])


def media_responses(accounts, role):
    client = accounts['clients'][role]
    owner_id = accounts['ids']['owner']
    paths = ['/api/arena', '/api/arena/players/' + owner_id, '/api/social/stories',
             '/api/friends', '/api/friends/players', '/api/messages/players',
             '/api/messages/conversations']
    paths += ['/api/social/feed?mode=' + mode
              for mode in ('global', 'country', 'state', 'for-you', 'local', 'following')]
    if role != 'owner':
        paths.append('/api/messages/conversations/' + owner_id)
    return [(path, client.get(path)) for path in paths]


def assert_hidden(accounts, role):
    for path, response in media_responses(accounts, role):
        assert response.status_code == 200, path
        for secret in accounts['secrets']:
            assert secret not in response.get_data(as_text=True), (role, path)
    profile = accounts['clients'][role].get('/api/arena/players/' + accounts['ids']['owner']).json
    assert profile['player']['photoPrivacy'] == 'friends'
    assert profile['player']['canViewPhotos'] is False
    assert profile['player']['mediaHidden'] is True
    assert all(not profile['player'].get(field) for field in ('image', 'avatar', 'cover'))
    assert [post['id'] for post in profile['posts']] == [accounts['text']['id']]
    assert profile['posts'][0]['avatar'] == ''
    assert profile['stories'] == []
    feed = accounts['clients'][role].get('/api/social/feed?mode=global').json
    assert accounts['photo']['id'] not in {post['id'] for post in feed['posts']}
    assert accounts['text']['id'] in {post['id'] for post in feed['posts']}


def assert_visible(accounts, role):
    client = accounts['clients'][role]
    profile = client.get('/api/arena/players/' + accounts['ids']['owner']).json
    assert profile['player']['canViewPhotos'] is True
    assert profile['player']['mediaHidden'] is False
    assert profile['player']['image'] == accounts['photo']['image']
    assert all(secret in str(profile) for secret in accounts['secrets'])
    assert {post['id'] for post in profile['posts']} == {accounts['photo']['id'], accounts['text']['id']}
    assert [story['id'] for story in profile['stories']] == [accounts['story']['id']]
    feed = client.get('/api/social/feed?mode=global').json
    assert accounts['photo']['id'] in {post['id'] for post in feed['posts']}
    assert accounts['story']['id'] in {story['id'] for story in feed['stories']}


def test_new_accounts_default_to_friends_only_photos(private_accounts):
    accounts = private_accounts
    with raw_state() as data:
        players = {player['id']: player for player in data['arena']['players']}
        assert all(players[player_id]['photoPrivacy'] == 'friends' for player_id in accounts['ids'].values())
    owner_profile = accounts['clients']['owner'].get('/api/arena/players/' + accounts['ids']['owner']).json
    assert owner_profile['player']['photoPrivacy'] == 'friends'
    assert_visible(accounts, 'owner')
    assert_hidden(accounts, 'stranger')


def test_legacy_accounts_without_a_setting_default_to_private_and_follow_friendship(private_accounts):
    accounts = private_accounts
    owner_id = accounts['ids']['owner']
    with raw_state() as data:
        next(player for player in data['arena']['players'] if player['id'] == owner_id).pop('photoPrivacy')
    assert_visible(accounts, 'owner')
    for role in ('friend', 'pending', 'stranger'):
        assert_hidden(accounts, role)
    path = '/api/friends/requests/' + accounts['requests']['friend']
    assert mutate(accounts['clients']['owner'], 'post', path, {'action': 'accept'}).status_code == 200
    assert_visible(accounts, 'friend')
    assert_hidden(accounts, 'pending')
    assert mutate(accounts['clients']['friend'], 'post', path, {'action': 'remove'}).status_code == 200
    assert_hidden(accounts, 'friend')
    with raw_state() as data:
        assert 'photoPrivacy' not in next(player for player in data['arena']['players'] if player['id'] == owner_id)


@pytest.mark.parametrize('stored_setting', [None, '', 'unexpected'])
def test_invalid_stored_privacy_settings_fail_closed(private_accounts, stored_setting):
    accounts = private_accounts
    with raw_state() as data:
        next(player for player in data['arena']['players'] if player['id'] == accounts['ids']['owner'])['photoPrivacy'] = stored_setting
    assert_visible(accounts, 'owner')
    assert_hidden(accounts, 'stranger')


def test_pending_and_unrelated_accounts_cannot_access_private_photos(private_accounts):
    accounts = private_accounts
    assert_visible(accounts, 'owner')
    for role in ('friend', 'pending', 'stranger'):
        assert_hidden(accounts, role)
    # Following or sharing a squad is insufficient permission.
    stranger = accounts['clients']['stranger']
    assert mutate(stranger, 'post', '/api/social/follow', {'name': 'Owner'}).status_code == 200
    with raw_state() as data:
        data['arena']['teams'][0]['members'].extend([accounts['ids']['owner'], accounts['ids']['stranger']])
    assert_hidden(accounts, 'stranger')


def test_acceptance_grants_reciprocal_access_and_removal_revokes_it(private_accounts):
    accounts = private_accounts
    owner, friend = accounts['clients']['owner'], accounts['clients']['friend']
    path = '/api/friends/requests/' + accounts['requests']['friend']
    response = mutate(owner, 'post', path, {'action': 'accept'})
    assert response.status_code == 200
    assert_visible(accounts, 'owner')
    assert_visible(accounts, 'friend')
    for endpoint in ('/api/friends', '/api/friends/players', '/api/messages/players',
                     '/api/messages/conversations', '/api/messages/conversations/' + accounts['ids']['owner']):
        assert accounts['secrets'][2] in friend.get(endpoint).get_data(as_text=True), endpoint
    assert_hidden(accounts, 'pending')
    assert_hidden(accounts, 'stranger')
    assert mutate(friend, 'post', path, {'action': 'remove'}).status_code == 200
    assert_hidden(accounts, 'friend')
    assert_visible(accounts, 'owner')


def test_private_photo_access_is_reciprocal_between_both_account_owners(private_accounts):
    accounts = private_accounts
    owner, friend = accounts['clients']['owner'], accounts['clients']['friend']
    friend_path = '/api/arena/players/' + accounts['ids']['friend']
    assert mutate(friend, 'patch', friend_path, {'avatar': upload('red'), 'photoPrivacy': 'friends'}).status_code == 200
    friend_avatar = friend.get(friend_path).json['player']['avatar']
    assert owner.get(friend_path).json['player']['avatar'] == ''
    request_path = '/api/friends/requests/' + accounts['requests']['friend']
    assert mutate(owner, 'post', request_path, {'action': 'accept'}).status_code == 200
    assert owner.get(friend_path).json['player']['avatar'] == friend_avatar
    assert_visible(accounts, 'friend')
    assert mutate(owner, 'post', request_path, {'action': 'remove'}).status_code == 200
    assert owner.get(friend_path).json['player']['avatar'] == ''
    assert_hidden(accounts, 'friend')


@pytest.mark.parametrize('action,payload', [('like', {}), ('save', {}),
    ('comments', {'text': 'Guessing the photo ID'}), ('reaction', {'reaction': 'fire'})])
def test_guessed_private_photo_actions_do_not_expose_or_mutate_media(private_accounts, action, payload):
    accounts = private_accounts
    stranger = accounts['clients']['stranger']
    path = '/api/social/posts/' + accounts['photo']['id'] + '/' + action
    response = mutate(stranger, 'post', path, payload)
    assert response.status_code == 404
    assert all(secret not in response.get_data(as_text=True) for secret in accounts['secrets'])
    with raw_state() as data:
        stored = next(post for post in data['posts'] if post['id'] == accounts['photo']['id'])
        assert stored['likes'] == 0 and stored['comments'] == []
        assert not stored.get('likedBy') and not stored.get('savedBy') and not stored.get('reactionsBy')
    text_path = '/api/social/posts/' + accounts['text']['id'] + '/' + action
    response = mutate(stranger, 'post', text_path, payload)
    assert response.status_code == 200
    assert response.json['avatar'] == ''
    assert all(secret not in response.get_data(as_text=True) for secret in accounts['secrets'])


def test_explicit_public_choice_persists_and_sample_profiles_remain_public(private_accounts):
    accounts = private_accounts
    owner_id = accounts['ids']['owner']
    owner = accounts['clients']['owner']
    path = '/api/arena/players/' + owner_id
    response = mutate(owner, 'patch', path, {'photoPrivacy': 'public'})
    assert response.status_code == 200
    with raw_state() as data:
        assert next(p for p in data['arena']['players'] if p['id'] == owner_id)['photoPrivacy'] == 'public'
    for role in accounts['clients']:
        assert_visible(accounts, role)
        assert accounts['clients'][role].get(path).json['player']['photoPrivacy'] == 'public'
    assert mutate(owner, 'patch', path, {'photoPrivacy': 'friends'}).status_code == 200
    assert_hidden(accounts, 'stranger')
    # Stored settings survive a separate authenticated session.
    other_session = app.test_client()
    assert mutate(other_session, 'post', '/api/auth/login', {
        'email': 'owner@example.com', 'password': 'long-photo-password'}).status_code == 200
    assert other_session.get(path).json['player']['photoPrivacy'] == 'friends'
    assert other_session.get(path).json['player']['canViewPhotos'] is True
    with raw_state() as data:
        assert next(p for p in data['arena']['players'] if p['id'] == owner_id)['photoPrivacy'] == 'friends'
        assert 'photoPrivacy' not in next(p for p in data['arena']['players'] if p['id'] == 'athlete-1')
    legacy = accounts['clients']['stranger'].get('/api/arena/players/athlete-1').json
    assert legacy['player']['photoPrivacy'] == 'public'
    assert legacy['player']['canViewPhotos'] is True and legacy['player']['image']
    assert legacy['posts'] and legacy['stories']


@pytest.mark.parametrize('invalid', ['', 'private', 'Friends', None, True, 7, [], {}])
def test_privacy_can_only_be_changed_by_owner_with_supported_values(private_accounts, invalid):
    accounts = private_accounts
    path = '/api/arena/players/' + accounts['ids']['owner']
    assert mutate(accounts['clients']['stranger'], 'patch', path, {'photoPrivacy': 'public'}).status_code == 403
    response = mutate(accounts['clients']['owner'], 'patch', path, {'photoPrivacy': invalid})
    assert response.status_code == 400
    assert accounts['clients']['owner'].get(path).json['player']['photoPrivacy'] == 'friends'
    assert_hidden(accounts, 'stranger')


def test_private_photos_require_authenticated_accounts(private_accounts):
    accounts = private_accounts
    anonymous = app.test_client()
    for path in ('/api/arena', '/api/arena/players/' + accounts['ids']['owner'],
                 '/api/social/feed', '/api/social/stories', '/api/friends/players', '/api/messages/players'):
        response = anonymous.get(path)
        assert response.status_code == 401
        assert all(secret not in response.get_data(as_text=True) for secret in accounts['secrets'])
