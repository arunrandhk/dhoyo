"""Photo access depends on the owner and accepted account friendships."""
from auth import current_user_id


PHOTO_FIELDS = ('image', 'avatar', 'cover')


def photo_privacy(player, data=None):
    if 'photoPrivacy' in player:
        # Keep an explicit public choice; an unexpected stored value fails closed.
        return 'public' if player['photoPrivacy'] == 'public' else 'friends'
    # Legacy account photos use the same private default as new accounts.
    # Seeded sample players remain public without exposing account metadata.
    if data is not None and any(account['player_id'] == player['id']
                                for account in data.get('accounts', {}).values()):
        return 'friends'
    return 'public'


def player_for(data, player_id):
    return next((player for player in data.get('arena', {}).get('players', [])
                 if player['id'] == player_id), None)


def can_view_photos(data, owner_id, viewer_id=None):
    viewer_id = current_user_id() if viewer_id is None else viewer_id
    owner = player_for(data, owner_id)
    if owner is None or photo_privacy(owner, data) == 'public' or owner_id == viewer_id:
        return True
    account_ids = {account['player_id'] for account in data.get('accounts', {}).values()}
    if owner_id not in account_ids or viewer_id not in account_ids:
        return False
    return any(item.get('status') == 'accepted' and
               {item.get('senderId'), item.get('recipientId')} == {owner_id, viewer_id}
               for item in data.get('friendRequests', []))


def public_photos(player, data):
    allowed = can_view_photos(data, player['id'])
    result = {**player, 'photoPrivacy': photo_privacy(player, data),
              'canViewPhotos': allowed, 'mediaHidden': not allowed}
    if not allowed:
        for key in PHOTO_FIELDS:
            result[key] = ''
    return result


def visible_photo_item(item, data):
    """Text posts stay public; a private photo post or story is omitted entirely."""
    return not item.get('image') or can_view_photos(data, item.get('authorId'))


def hidden_photo_values(data):
    """Track copied photo URIs, including legacy community preview aliases."""
    hidden = set()
    private_ids = set()
    for player in data.get('arena', {}).get('players', []):
        if not can_view_photos(data, player['id']):
            private_ids.add(player['id'])
            hidden.update(player.get(key) for key in PHOTO_FIELDS if player.get(key))
    for item in data.get('posts', []) + data.get('stories', []):
        if item.get('authorId') in private_ids:
            hidden.update(item.get(key) for key in PHOTO_FIELDS if item.get(key))
    return hidden


def redact_photo_aliases(value, data):
    """A copied photo never bypasses the owner's access setting in API output."""
    hidden = hidden_photo_values(data)

    def redact(item):
        if isinstance(item, dict):
            return {key: redact(child) for key, child in item.items()}
        if isinstance(item, list):
            return [redact(child) for child in item]
        if isinstance(item, str) and item in hidden:
            return ''
        return item

    return redact(value)
