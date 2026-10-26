"""Private sticker conversations between registered player accounts."""
import json
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request

from auth import current_user_id
from arena import ensure_arena
from social import now, raw_state
from privacy import can_view_photos, redact_photo_aliases


messages = Blueprint('messages', __name__, url_prefix='/api/messages')
MESSAGE_FIELDS = ('id', 'senderId', 'recipientId', 'stickerId', 'createdAt')
PLAYER_FIELDS = ('id', 'name', 'initials', 'avatar', 'sport')


def registered_players(data):
    from auth import pending_account_ids
    account_ids = {account['player_id'] for account in data.get('accounts', {}).values()} - pending_account_ids(data)
    return {player['id']: player for player in ensure_arena(data)['players']
            if player['id'] in account_ids}


def public_player(player, data):
    result = {key: player.get(key, '') for key in PLAYER_FIELDS}
    if not can_view_photos(data, player['id']):
        result['avatar'] = ''
    return redact_photo_aliases(result, data)


def public_message(message):
    return {key: message[key] for key in MESSAGE_FIELDS}


def target_player(data, player_id):
    if player_id == current_user_id():
        return None, (jsonify(error='Choose another player to send a sticker'), 400)
    player = registered_players(data).get(player_id)
    if not player:
        return None, (jsonify(error='Player account not found'), 404)
    return player, None


def sticker_ids():
    """The frontend catalog is also the authoritative send whitelist."""
    catalog = Path(current_app.static_folder) / 'sportspace' / 'stickers.json'
    with catalog.open(encoding='utf-8') as source:
        return {sticker['id'] for sticker in json.load(source)['stickers']}


@messages.get('/players')
def players():
    user_id = current_user_id()
    query = request.args.get('q', '').strip().casefold()
    with raw_state() as data:
        values = [public_player(player, data) for player_id, player in registered_players(data).items()
                  if player_id != user_id and
                  (not query or query in (player['name'] + ' ' + player['sport']).casefold())]
        values.sort(key=lambda player: (player['name'].casefold(), player['id']))
        return jsonify(players=values, currentUserId=user_id)


@messages.get('/conversations')
def conversations():
    user_id = current_user_id()
    with raw_state() as data:
        players_by_id = registered_players(data)
        grouped = {}
        for message in data.get('stickerMessages', []):
            if message['senderId'] == user_id:
                other_id = message['recipientId']
            elif message['recipientId'] == user_id:
                other_id = message['senderId']
            else:
                continue
            if other_id not in players_by_id:
                continue
            grouped.setdefault(other_id, []).append(message)
        values = []
        for player_id, conversation in grouped.items():
            latest = max(conversation, key=lambda item: (item['createdAt'], item['id']))
            unread = sum(message['recipientId'] == user_id and not message.get('readAt')
                         for message in conversation)
            values.append(dict(player=public_player(players_by_id[player_id], data),
                               lastMessage=public_message(latest), unreadCount=unread))
        values.sort(key=lambda item: (item['lastMessage']['createdAt'], item['lastMessage']['id']), reverse=True)
        return jsonify(conversations=values, unreadCount=sum(item['unreadCount'] for item in values))


@messages.get('/conversations/<player_id>')
def conversation(player_id):
    user_id = current_user_id()
    with raw_state() as data:
        player, error = target_player(data, player_id)
        if error:
            return error
        values = [message for message in data.get('stickerMessages', [])
                  if (message['senderId'] == user_id and message['recipientId'] == player_id) or
                  (message['senderId'] == player_id and message['recipientId'] == user_id)]
        read_at = now().isoformat()
        for message in values:
            if message['recipientId'] == user_id and not message.get('readAt'):
                message['readAt'] = read_at
        values.sort(key=lambda item: (item['createdAt'], item['id']))
        return jsonify(player=public_player(player, data), messages=[public_message(message) for message in values],
                       currentUserId=user_id)


@messages.post('/conversations/<player_id>')
def send_sticker(player_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'stickerId'}:
        return jsonify(error='Send a stickerId from the sticker collection'), 400
    sticker_id = payload['stickerId']
    if not isinstance(sticker_id, str) or sticker_id not in sticker_ids():
        return jsonify(error='Choose a sticker from the sticker collection'), 400
    with raw_state() as data:
        _, error = target_player(data, player_id)
        if error:
            return error
        message = dict(id='message-' + uuid4().hex, senderId=current_user_id(), recipientId=player_id,
                       stickerId=sticker_id, createdAt=now().isoformat(), readAt=None)
        data.setdefault('stickerMessages', []).append(message)
        return jsonify(message=public_message(message)), 201
