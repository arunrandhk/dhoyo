"""Earned player milestones from organisation-owned tournament registrations.

The journal is updated inside the same state transaction as its source records.
Completed participation is immutable; open registrations are reconciled so a
withdrawal, cancellation or roster removal cannot count towards a season.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request

from organisations import ServiceError, actor
from privacy import can_view_photos, redact_photo_aliases
from social import SPORTS, raw_state


progression = Blueprint('progression', __name__, url_prefix='/api/progression')
BADGES = (
    ('first-team', 'Team ready', 'Register for your first tournament team.', 'registered', 1),
    ('first-tournament', 'First finish', 'Be on the roster when an organiser completes a tournament.', 'completed', 1),
    ('five-tournaments', 'Keep showing up', 'Participate in five completed tournaments.', 'completed', 5),
    ('multi-sport', 'Across the field', 'Participate in completed tournaments in two different sports.', 'sports', 2),
)


@progression.errorhandler(ServiceError)
def service_error(error):
    return jsonify(error=str(error)), error.status


def now():
    return datetime.now(timezone.utc)


def parsed_instant(value):
    try:
        if not isinstance(value, str) or len(value) > 80:
            return None
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def season_for(timestamp):
    timestamp = timestamp.astimezone(timezone.utc)
    return f'{timestamp.year:04d}-Q{(timestamp.month - 1) // 3 + 1}'


def season_details(season):
    if not isinstance(season, str) or not re.fullmatch(r'[2-9][0-9]{3}-Q[1-4]', season):
        raise ServiceError('Choose a season in YYYY-Q1 to YYYY-Q4 format')
    year, quarter = int(season[:4]), int(season[-1])
    if year >= 9999:
        raise ServiceError('Choose a season before year 9999')
    month = (quarter - 1) * 3 + 1
    end_year, end_month = (year + 1, 1) if quarter == 4 else (year, month + 3)
    return dict(id=season, label=f'Q{quarter} {year} · UTC',
                startsAt=datetime(year, month, 1, tzinfo=timezone.utc).isoformat(),
                endsAt=datetime(end_year, end_month, 1, tzinfo=timezone.utc).isoformat(),
                timezone='UTC')


def player_accounts(data):
    """Synthetic arena players and organisation accounts never earn progress."""
    return {account['player_id']: (email.strip().casefold(), account)
            for email, account in data.get('accounts', {}).items()
            if account.get('account_type', 'player') == 'player' and account.get('player_id')
            and account.get('email_verified', True)}


def sync_progress(data):
    """Reconcile sources idempotently while the caller holds raw_state's lock.

    Roster email -> account ID bindings survive an account email change. A
    removed roster entry stops counting before completion. Only verified roster
    entries (including acknowledged activation links) can bind to an account.
    An email-only invite is bound after its recipient creates a player account.
    """
    journal = data.setdefault('playerProgress', {})
    registered = journal.setdefault('registrations', {})
    completed = journal.setdefault('completions', {})
    bindings = journal.setdefault('rosterBindings', {})
    for entry in registered.values():
        entry['active'] = False
    service = data.get('organisationService', {})
    accounts = player_accounts(data)
    email_ids = {email: player_id for player_id, (email, _) in accounts.items()}
    owner_accounts = {account['player_id']: account
                      for account in data.get('accounts', {}).values()
                      if account.get('account_type') == 'organisation' and account.get('player_id')
                      and account.get('email_verified', True)}
    organisations = {item.get('id'): item for item in service.get('organisations', [])
                     if item.get('ownerId') in owner_accounts and
                     owner_accounts[item['ownerId']].get('organisation_id', item.get('id')) == item.get('id')}
    tournaments = {item.get('id'): item for item in service.get('tournaments', [])
                   if item.get('organisationId') in organisations and
                   item.get('status') in ('open', 'live', 'completed') and
                   item.get('sport') in SPORTS}
    recorded_at = now().isoformat()
    for registration in service.get('registrations', []):
        tournament = tournaments.get(registration.get('tournamentId'))
        starts = parsed_instant(tournament.get('startsAt')) if tournament else None
        if (not tournament or not starts or registration.get('status') != 'registered'
                or not registration.get('id') or registration.get('playerId') not in accounts):
            continue
        members = {registration['playerId']}
        saved_bindings = bindings.setdefault(registration['id'], {})
        for roster in registration.get('playerEmails', []):
            if not roster.get('verified') and roster.get('acknowledgementStatus') != 'acknowledged':
                continue
            email = roster.get('email')
            if not isinstance(email, str):
                continue
            email = email.strip().casefold()
            player_id = saved_bindings.get(email) or email_ids.get(email)
            if player_id in accounts:
                saved_bindings[email] = player_id
                members.add(player_id)
        for player_id in members:
            key = tournament['id'] + ':' + player_id
            entry = registered.setdefault(key, dict(
                playerId=player_id, tournamentId=tournament['id'],
                sport=tournament['sport'], season=season_for(starts),
                earnedAt=registration.get('createdAt') or recorded_at))
            entry['active'] = True
            if tournament['status'] == 'completed' and key not in completed:
                completion_time = parsed_instant(tournament.get('completedAt')) or starts
                completed[key] = dict(playerId=player_id, tournamentId=tournament['id'],
                                      sport=tournament['sport'], season=season_for(starts),
                                      earnedAt=completion_time.isoformat(), registeredAt=entry['earnedAt'])
    return journal


def records_for(journal, player_id, collection, season=None, sport=None):
    return [entry for entry in journal[collection].values()
            if entry['playerId'] == player_id and
            (collection != 'registrations' or entry.get('active')) and
            (season is None or entry['season'] == season) and
            (sport is None or entry['sport'] == sport)]


def totals(journal, player_id, season=None, sport=None):
    completed = records_for(journal, player_id, 'completions', season, sport)
    registered = records_for(journal, player_id, 'registrations', season, sport)
    return dict(registeredTournaments=len({item['tournamentId'] for item in registered + completed}),
                completedTournaments=len(completed), sportsCompleted=len({item['sport'] for item in completed}))


def badges_for(journal, player_id):
    registrations = records_for(journal, player_id, 'registrations')
    completions = sorted(records_for(journal, player_id, 'completions'),
                         key=lambda item: (item['earnedAt'], item['tournamentId']))
    first_sports = {}
    for item in completions:
        first_sports.setdefault(item['sport'], item['earnedAt'])
    timestamps = dict(registered=sorted([item['earnedAt'] for item in registrations] +
                                       [item.get('registeredAt', item['earnedAt']) for item in completions]),
                      completed=[item['earnedAt'] for item in completions],
                      sports=sorted(first_sports.values()))
    return [dict(id=badge_id, name=name, description=description, target=target,
                 progress=min(target, len(timestamps[metric])), unlocked=len(timestamps[metric]) >= target,
                 earnedAt=timestamps[metric][target - 1] if len(timestamps[metric]) >= target else None)
            for badge_id, name, description, metric, target in BADGES]


def available_seasons(journal):
    current = now()
    year, quarter = current.year, (current.month - 1) // 3 + 1
    seasons = set()
    for _ in range(4):
        seasons.add(f'{year:04d}-Q{quarter}')
        year, quarter = (year - 1, 4) if quarter == 1 else (year, quarter - 1)
    for collection in ('registrations', 'completions'):
        seasons.update(entry['season'] for entry in journal[collection].values()
                       if collection == 'completions' or entry.get('active'))
    return [season_details(season) for season in sorted(seasons, reverse=True)]


def safe_avatar(value):
    if not isinstance(value, str):
        return ''
    if re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+', value) and len(value) <= 2_000_000:
        return value
    try:
        parsed = urlsplit(value)
        if len(value) <= 2048 and parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return ''


@progression.get('/me')
def my_progress():
    if request.args:
        raise ServiceError('Your progress does not accept player or filter parameters')
    with raw_state() as data:
        visitor = actor(data, 'player')
        journal = sync_progress(data)
        season = season_for(now())
        return jsonify(playerId=visitor['id'], currentSeason=season_details(season),
                       stats=totals(journal, visitor['id']),
                       seasonStats=totals(journal, visitor['id'], season),
                       achievements=badges_for(journal, visitor['id']))


@progression.get('/leaderboard')
def seasonal_leaderboard():
    if set(request.args) - {'season', 'sport'} or any(len(request.args.getlist(key)) != 1 for key in request.args):
        raise ServiceError('Choose one season and one sport')
    season = request.args.get('season', season_for(now()))
    selected_season = season_details(season)
    sport = request.args.get('sport', 'All sports')
    if sport != 'All sports' and sport not in SPORTS:
        raise ServiceError('Choose a valid sport')
    with raw_state() as data:
        visitor = actor(data)
        journal = sync_progress(data)
        accounts = player_accounts(data)
        players = {player['id']: player for player in data.get('arena', {}).get('players', [])
                   if player['id'] in accounts}
        rows = []
        for player_id, player in players.items():
            counts = totals(journal, player_id, season, None if sport == 'All sports' else sport)
            if not counts['registeredTournaments']:
                continue
            rows.append(dict(playerId=player_id, name=player.get('name', 'Player'),
                             initials=player.get('initials', 'P'), sport=player.get('sport', ''),
                             avatar=safe_avatar(player.get('avatar')) if can_view_photos(data, player_id) else '',
                             **counts))
        rows.sort(key=lambda row: (-row['completedTournaments'], -row['registeredTournaments'],
                                   row['name'].casefold(), row['playerId']))
        previous_score, rank = None, 0
        my_rank = None
        for index, row in enumerate(rows):
            score = row['completedTournaments'], row['registeredTournaments']
            if score != previous_score:
                rank = index + 1
            row['rank'] = rank
            previous_score = score
            if row['playerId'] == visitor['id']:
                my_rank = rank
        return jsonify(currentUserId=visitor['id'], season=selected_season, sport=sport,
                       seasons=available_seasons(journal), sports=sorted(SPORTS),
                       players=redact_photo_aliases(rows[:100], data), totalPlayers=len(rows),
                       myRank=my_rank,
                       rankingRule='Completed tournaments first, then registered tournaments. Equal totals share a rank.')
