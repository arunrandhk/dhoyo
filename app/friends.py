"""Private friend requests and reciprocal friendships between player accounts."""
from uuid import uuid4

from flask import Blueprint, jsonify, request

from auth import current_user_id
from messages import public_player, registered_players
from social import now, raw_state


friends = Blueprint('friends', __name__, url_prefix='/api/friends')
REQUEST_FIELDS = ('id', 'senderId', 'recipientId', 'status', 'createdAt')
ACTIVE_STATUSES = {'pending', 'accepted'}


def relationships(data, user_id, players_by_id):
    """Return only the visitor's active relationships with registered accounts."""
    values = []
    for item in data.get('friendRequests', []):
        if item['status'] not in ACTIVE_STATUSES:
            continue
        if item['senderId'] == user_id:
            other_id = item['recipientId']
        elif item['recipientId'] == user_id:
            other_id = item['senderId']
        else:
            continue
        if other_id in players_by_id:
            values.append((item, players_by_id[other_id]))
    return values


def public_request(item, player, data):
    return {**{key: item[key] for key in REQUEST_FIELDS}, 'player': public_player(player, data)}


def public_overview(data, user_id):
    connected, incoming, outgoing = [], [], []
    for item, player in relationships(data, user_id, registered_players(data)):
        if item['status'] == 'accepted':
            connected.append({**public_player(player, data), 'requestId': item['id']})
        elif item['recipientId'] == user_id:
            incoming.append(public_request(item, player, data))
        else:
            outgoing.append(public_request(item, player, data))
    connected.sort(key=lambda player: (player['name'].casefold(), player['id']))
    for values in (incoming, outgoing):
        values.sort(key=lambda item: (item['createdAt'], item['id']), reverse=True)
    return dict(currentUserId=user_id, friends=connected, incoming=incoming,
                outgoing=outgoing, incomingCount=len(incoming))


@friends.get('')
def overview():
    with raw_state() as data:
        return jsonify(public_overview(data, current_user_id()))


@friends.get('/players')
def players():
    user_id = current_user_id()
    query = request.args.get('q', '').strip().casefold()
    with raw_state() as data:
        players_by_id = registered_players(data)
        existing = {}
        for item, player in relationships(data, user_id, players_by_id):
            state = 'friends' if item['status'] == 'accepted' else (
                'outgoing' if item['senderId'] == user_id else 'incoming')
            existing[player['id']] = dict(friendship=state, requestId=item['id'])
        values = [{**public_player(player, data),
                   **existing.get(player_id, dict(friendship='none', requestId=None))}
                  for player_id, player in players_by_id.items()
                  if player_id != user_id and
                  (not query or query in (player['name'] + ' ' + player['sport']).casefold())]
        values.sort(key=lambda player: (player['name'].casefold(), player['id']))
        return jsonify(currentUserId=user_id, players=values)


@friends.post('/requests')
def send_request():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'playerId'}:
        return jsonify(error='Choose a player to send a friend request'), 400
    player_id = payload['playerId']
    if not isinstance(player_id, str) or not player_id or len(player_id) > 100:
        return jsonify(error='Choose a player to send a friend request'), 400
    user_id = current_user_id()
    if player_id == user_id:
        return jsonify(error='Choose another player to send a friend request'), 400
    with raw_state() as data:
        player = registered_players(data).get(player_id)
        if not player:
            return jsonify(error='Player account not found'), 404
        pair = {user_id, player_id}
        for item in data.get('friendRequests', []):
            if item['status'] in ACTIVE_STATUSES and {item['senderId'], item['recipientId']} == pair:
                error = 'You are already friends' if item['status'] == 'accepted' else 'A friend request is already pending'
                return jsonify(error=error), 409
        item = dict(id='friend-request-' + uuid4().hex, senderId=user_id,
                    recipientId=player_id, status='pending', createdAt=now().isoformat())
        data.setdefault('friendRequests', []).append(item)
        return jsonify(**public_overview(data, user_id), request=public_request(item, player, data)), 201


@friends.post('/requests/<request_id>')
def respond(request_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'action'}:
        return jsonify(error='Choose accept, decline, cancel or remove'), 400
    action = payload['action']
    if not isinstance(action, str) or action not in {'accept', 'decline', 'cancel', 'remove'}:
        return jsonify(error='Choose accept, decline, cancel or remove'), 400
    user_id = current_user_id()
    with raw_state() as data:
        item = next((value for value in data.get('friendRequests', [])
                     if value['id'] == request_id and user_id in (value['senderId'], value['recipientId'])), None)
        if not item:
            return jsonify(error='Friend request not found'), 404
        if action in ('accept', 'decline') and item['recipientId'] != user_id:
            return jsonify(error='Only the recipient can respond to this friend request'), 403
        if action == 'cancel' and item['senderId'] != user_id:
            return jsonify(error='Only the sender can cancel this friend request'), 403
        expected_status = 'accepted' if action == 'remove' else 'pending'
        if item['status'] != expected_status:
            return jsonify(error='This friend request has already changed'), 409
        item['status'] = {'accept': 'accepted', 'decline': 'declined',
                          'cancel': 'cancelled', 'remove': 'removed'}[action]
        item['updatedAt'] = now().isoformat()
        return jsonify(public_overview(data, user_id))
