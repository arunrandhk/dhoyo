from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app
from social import raw_state


HEADERS = {'X-Dhoyo-Request': '1'}
PLAYER_FIELDS = {'id', 'name', 'initials', 'avatar', 'sport'}
OVERVIEW_FIELDS = {'currentUserId', 'friends', 'incoming', 'outgoing', 'incomingCount'}


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'friends.sqlite'))
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    return app.test_client(), app.test_client(), app.test_client()


def register(client, name):
    response = client.post('/api/auth/register', json=dict(
        name=name, email=name.lower() + '@example.com', password='my-long-password',
        sport='Football', city='Delhi', state='Delhi', country='India'), headers=HEADERS)
    assert response.status_code == 201
    return response.json['userId']


def send(client, player_id, **extra):
    return client.post('/api/friends/requests', json={'playerId': player_id, **extra}, headers=HEADERS)


def respond(client, request_id, action, **extra):
    return client.post('/api/friends/requests/' + request_id,
                       json={'action': action, **extra}, headers=HEADERS)


def directory(client):
    return {player['id']: player for player in client.get('/api/friends/players').json['players']}


def test_directory_lists_only_other_accounts_and_public_fields(clients):
    a, b, c = clients
    aid, bid, cid = register(a, 'Alex'), register(b, 'Sam'), register(c, 'Taylor')
    result = a.get('/api/friends/players').json
    assert result['currentUserId'] == aid
    assert [player['id'] for player in result['players']] == [bid, cid]
    assert all(set(player) == PLAYER_FIELDS | {'friendship', 'requestId'} for player in result['players'])
    assert all(player['friendship'] == 'none' and player['requestId'] is None for player in result['players'])
    assert a.get('/api/friends/players?q=%20SAM%20').json['players'][0]['id'] == bid
    assert len(a.get('/api/friends/players?q=football').json['players']) == 2
    assert a.get('/api/friends/players?q=unknown').json['players'] == []
    assert a.get('/api/friends').json == dict(currentUserId=aid, friends=[], incoming=[], outgoing=[], incomingCount=0)


def test_request_acceptance_is_reciprocal_and_private(clients):
    a, b, c = clients
    aid, bid, cid = register(a, 'Alex'), register(b, 'Sam'), register(c, 'Taylor')
    result = send(a, bid)
    assert result.status_code == 201
    assert set(result.json) == OVERVIEW_FIELDS | {'request'}
    item = result.json['request']
    assert set(item) == {'id', 'senderId', 'recipientId', 'status', 'createdAt', 'player'}
    assert item['senderId'] == aid and item['recipientId'] == bid and item['status'] == 'pending'
    assert set(item['player']) == PLAYER_FIELDS and item['player']['id'] == bid
    assert result.json['outgoing'] == [item]
    assert result.json['incomingCount'] == 0
    incoming = b.get('/api/friends').json
    assert incoming['incomingCount'] == 1
    assert incoming['incoming'][0]['id'] == item['id']
    assert incoming['incoming'][0]['player']['id'] == aid
    assert incoming['outgoing'] == [] and incoming['friends'] == []
    assert directory(a)[bid]['friendship'] == 'outgoing'
    assert directory(b)[aid]['friendship'] == 'incoming'
    assert directory(c)[aid]['friendship'] == directory(c)[bid]['friendship'] == 'none'
    assert c.get('/api/friends').json == dict(currentUserId=cid, friends=[], incoming=[], outgoing=[], incomingCount=0)

    accepted = respond(b, item['id'], 'accept')
    assert accepted.status_code == 200 and set(accepted.json) == OVERVIEW_FIELDS
    assert accepted.json['incomingCount'] == 0 and accepted.json['incoming'] == []
    assert accepted.json['friends'][0]['id'] == aid
    assert set(accepted.json['friends'][0]) == PLAYER_FIELDS | {'requestId'}
    for client, peer_id in ((a, bid), (b, aid)):
        overview = client.get('/api/friends').json
        assert overview['incoming'] == overview['outgoing'] == []
        assert overview['friends'][0]['id'] == peer_id
        assert overview['friends'][0]['requestId'] == item['id']
        assert directory(client)[peer_id]['friendship'] == 'friends'
        assert directory(client)[peer_id]['requestId'] == item['id']
        assert send(client, peer_id).status_code == 409
    assert c.get('/api/friends').json['friends'] == []


def test_only_participants_with_correct_roles_can_change_requests(clients):
    a, b, c = clients
    aid, bid = register(a, 'Alex'), register(b, 'Sam')
    register(c, 'Taylor')
    request_id = send(a, bid).json['request']['id']
    for action in ('accept', 'decline', 'cancel', 'remove'):
        assert respond(c, request_id, action).status_code == 404
    assert respond(a, request_id, 'accept').status_code == 403
    assert respond(a, request_id, 'decline').status_code == 403
    assert respond(b, request_id, 'cancel').status_code == 403
    assert respond(a, request_id, 'remove').status_code == 409
    assert respond(b, request_id, 'remove').status_code == 409
    assert respond(b, request_id, 'accept').status_code == 200
    assert respond(b, request_id, 'accept').status_code == 409
    assert respond(b, request_id, 'decline').status_code == 409
    assert respond(a, request_id, 'cancel').status_code == 409
    assert respond(c, request_id, 'remove').status_code == 404
    assert respond(b, request_id, 'remove').status_code == 200
    assert a.get('/api/friends').json['friends'] == []
    assert b.get('/api/friends').json['friends'] == []
    assert respond(a, request_id, 'remove').status_code == 409
    assert respond(a, 'unknown-request', 'remove').status_code == 404
    assert directory(a)[bid]['friendship'] == 'none'
    assert directory(b)[aid]['requestId'] is None
    # Either party may remove an accepted friendship.
    new_id = send(b, aid).json['request']['id']
    assert respond(a, new_id, 'accept').status_code == 200
    assert respond(b, new_id, 'remove').status_code == 200


@pytest.mark.parametrize('action,actor', [('decline', 1), ('cancel', 0)])
def test_decline_and_cancel_clear_pending_requests_and_allow_resending(clients, action, actor):
    a, b, _ = clients
    aid, bid = register(a, 'Alex'), register(b, 'Sam')
    request_id = send(a, bid).json['request']['id']
    assert send(a, bid).status_code == 409
    assert send(b, aid).status_code == 409
    response = respond(clients[actor], request_id, action)
    assert response.status_code == 200
    assert response.json['incoming'] == response.json['outgoing'] == response.json['friends'] == []
    assert response.json['incomingCount'] == 0
    assert b.get('/api/friends').json['incomingCount'] == 0
    assert directory(a)[bid]['friendship'] == directory(b)[aid]['friendship'] == 'none'
    assert respond(clients[actor], request_id, action).status_code == 409
    new_request = send(b, aid)
    assert new_request.status_code == 201
    assert new_request.json['request']['id'] != request_id


def test_account_identity_and_strict_payload_validation(clients):
    a, b, c = clients
    aid, bid, cid = register(a, 'Alex'), register(b, 'Sam'), register(c, 'Taylor')
    assert send(a, aid).status_code == 400
    for player_id in ('unknown-player', 'athlete-1', 'demo-user'):
        assert send(a, player_id).status_code == 404
    for player_id in ('', None, 12, [], {}, 'p' * 101):
        assert send(a, player_id).status_code == 400
    assert send(a, bid, senderId=cid).status_code == 400
    assert send(a, bid, recipientId=cid).status_code == 400
    for payload in ({}, [], {'playerId': bid, 'action': 'accept'}):
        assert a.post('/api/friends/requests', json=payload, headers=HEADERS).status_code == 400
    for raw_json in ('null', '{broken', '"player"'):
        assert a.post('/api/friends/requests', data=raw_json,
                      content_type='application/json', headers=HEADERS).status_code == 400
    assert b.get('/api/friends').json['incomingCount'] == 0
    request_id = send(a, bid).json['request']['id']
    for action in ('unknown', '', None, 12, [], {}):
        assert respond(b, request_id, action).status_code == 400
    assert respond(b, request_id, 'accept', playerId=cid).status_code == 400
    for payload in ({}, [], {'action': 'accept', 'senderId': cid}):
        assert b.post('/api/friends/requests/' + request_id, json=payload, headers=HEADERS).status_code == 400
    assert b.get('/api/friends').json['incomingCount'] == 1
    assert b.get('/api/friends').json['incoming'][0]['senderId'] == aid


def test_authentication_and_csrf_controls_apply_to_friends(clients):
    a, b, anonymous = clients
    aid, bid = register(a, 'Alex'), register(b, 'Sam')
    for path in ('/api/friends', '/api/friends/players'):
        assert anonymous.get(path).status_code == 401
    assert send(anonymous, bid).status_code == 401
    assert respond(anonymous, 'unknown-request', 'accept').status_code == 401
    for headers in ({}, {**HEADERS, 'Origin': 'https://evil.example'},
                    {**HEADERS, 'Sec-Fetch-Site': 'cross-site'}):
        assert a.post('/api/friends/requests', json={'playerId': bid}, headers=headers).status_code == 403
    assert b.get('/api/friends').json['incomingCount'] == 0
    request_id = send(a, bid).json['request']['id']
    assert b.post('/api/friends/requests/' + request_id, json={'action': 'accept'}).status_code == 403
    assert b.get('/api/friends').json['incomingCount'] == 1
    assert a.get('/api/friends').json['currentUserId'] == aid


def test_pending_and_accepted_relationships_survive_new_sessions(clients):
    a, b, c = clients
    aid, bid, cid = register(a, 'Alex'), register(b, 'Sam'), register(c, 'Taylor')
    accepted_id = send(a, bid).json['request']['id']
    assert respond(b, accepted_id, 'accept').status_code == 200
    pending_id = send(c, aid).json['request']['id']
    for client in clients:
        assert client.post('/api/auth/logout', json={}, headers=HEADERS).status_code == 200
    new_clients = [app.test_client() for _ in clients]
    for client, email in zip(new_clients, ('alex@example.com', 'sam@example.com', 'taylor@example.com')):
        assert client.post('/api/auth/login', json={'email': email, 'password': 'my-long-password'},
                           headers=HEADERS).status_code == 200
    a, b, c = new_clients
    overview = a.get('/api/friends').json
    assert overview['friends'][0]['id'] == bid
    assert overview['friends'][0]['requestId'] == accepted_id
    assert overview['incomingCount'] == 1
    assert overview['incoming'][0]['id'] == pending_id and overview['incoming'][0]['player']['id'] == cid
    assert b.get('/api/friends').json['friends'][0]['id'] == aid
    assert c.get('/api/friends').json['outgoing'][0]['id'] == pending_id
    with raw_state() as data:
        assert {item['id']: item['status'] for item in data['friendRequests']} == {
            accepted_id: 'accepted', pending_id: 'pending'}


def test_friendship_changes_leave_following_teams_support_and_awards_independent(clients):
    a, b, _ = clients
    register(a, 'Alex')
    bid = register(b, 'Sam')
    with raw_state() as data:
        arena = deepcopy(data['arena'])
        preferences = deepcopy(data['userPreferences'])
    request_id = send(a, bid).json['request']['id']
    assert respond(b, request_id, 'accept').status_code == 200
    assert respond(a, request_id, 'remove').status_code == 200
    with raw_state() as data:
        assert data['arena'] == arena
        assert data['userPreferences'] == preferences


def test_simultaneous_opposite_requests_create_one_relationship(clients):
    a, b, _ = clients
    aid, bid = register(a, 'Alex'), register(b, 'Sam')
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(send, a, bid)
        second = executor.submit(send, b, aid)
        statuses = sorted([first.result().status_code, second.result().status_code])
    assert statuses == [201, 409]
    with raw_state() as data:
        assert len(data['friendRequests']) == 1
        assert data['friendRequests'][0]['status'] == 'pending'
    assert len(a.get('/api/friends').json['incoming']) + len(a.get('/api/friends').json['outgoing']) == 1
    assert len(b.get('/api/friends').json['incoming']) + len(b.get('/api/friends').json['outgoing']) == 1


def test_profiles_show_reciprocal_accepted_friends_without_pending_or_ended_requests(clients):
    a, b, c = clients
    aid, bid, cid = register(a, 'Alex'), register(b, 'Sam'), register(c, 'Taylor')
    request_id = send(a, bid).json['request']['id']
    # An unrelated visitor sees the public accepted circle, never pending requests.
    for player_id in (aid, bid):
        assert c.get('/api/arena/players/' + player_id).json['connections'] == []
    assert respond(b, request_id, 'accept').status_code == 200
    for player_id, peer_id in ((aid, bid), (bid, aid)):
        connections = c.get('/api/arena/players/' + player_id).json['connections']
        assert len(connections) == 1
        assert connections[0]['playerId'] == connections[0]['player']['id'] == peer_id
        assert connections[0]['friend'] is True
        assert connections[0]['teamIds'] == connections[0]['matchIds'] == []

    pending_id = send(c, aid).json['request']['id']
    assert [item['playerId'] for item in b.get('/api/arena/players/' + aid).json['connections']] == [bid]
    assert respond(a, pending_id, 'decline').status_code == 200
    cancelled_id = send(c, aid).json['request']['id']
    assert respond(c, cancelled_id, 'cancel').status_code == 200
    # Legacy or orphaned state must not add unregistered accounts to the circle.
    with raw_state() as data:
        data['friendRequests'].append(dict(id='invalid-demo-friend', senderId=aid,
                                          recipientId='athlete-1', status='accepted', createdAt='2026-01-01'))
    assert [item['playerId'] for item in c.get('/api/arena/players/' + aid).json['connections']] == [bid]
    assert respond(a, request_id, 'remove').status_code == 200
    for player_id in (aid, bid, cid):
        assert c.get('/api/arena/players/' + player_id).json['connections'] == []


def test_profile_friendship_merges_existing_squad_and_match_connections(clients):
    a, b, c = clients
    aid, bid = register(a, 'Alex'), register(b, 'Sam')
    register(c, 'Taylor')
    with raw_state() as data:
        team = deepcopy(data['arena']['teams'][0])
        team.update(id='friend-team', ownerId=aid, members=[aid, bid], requests=[])
        data['arena']['teams'].append(team)
        match = deepcopy(data['arena']['matches'][0])
        match.update(id='friend-match', participantIds=[aid, bid])
        data['arena']['matches'].append(match)
    request_id = send(a, bid).json['request']['id']
    pending = c.get('/api/arena/players/' + aid).json['connections']
    assert len(pending) == 1 and not pending[0].get('friend')
    assert respond(b, request_id, 'accept').status_code == 200
    for player_id, peer_id in ((aid, bid), (bid, aid)):
        connections = c.get('/api/arena/players/' + player_id).json['connections']
        assert len(connections) == 1
        assert connections[0]['playerId'] == peer_id and connections[0]['friend'] is True
        assert connections[0]['teamIds'] == ['friend-team']
        assert connections[0]['matchIds'] == ['friend-match']
    assert respond(b, request_id, 'remove').status_code == 200
    connections = c.get('/api/arena/players/' + aid).json['connections']
    assert len(connections) == 1 and connections[0]['playerId'] == bid
    assert not connections[0].get('friend')
    assert connections[0]['teamIds'] == ['friend-team'] and connections[0]['matchIds'] == ['friend-match']


def test_profile_identifies_registered_accounts_for_direct_friend_actions(clients):
    a, b, _ = clients
    aid = register(a, 'Alex')
    # A profile loaded before a later account joins must not be the directory source.
    assert a.get('/api/arena/players/' + aid).json['registeredPlayer'] is True
    bid = register(b, 'Sam')
    profile = a.get('/api/arena/players/' + bid).json
    assert profile['registeredPlayer'] is True
    assert profile['player']['id'] == bid
    assert 'password_hash' not in profile['player'] and 'email' not in profile['player']
    assert a.get('/api/arena/players/athlete-1').json['registeredPlayer'] is False
    assert a.get('/api/arena/players/demo-user').json['registeredPlayer'] is False
