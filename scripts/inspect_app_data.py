#!/usr/bin/env python3
"""Read saved app records without exposing accounts, sessions or photo data."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys


def read_state(sqlite_path):
    if sqlite_path:
        path = Path(sqlite_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f'Database file does not exist: {path}')
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.execute('PRAGMA query_only = ON')
            row = connection.execute('SELECT payload FROM demo_state WHERE id = 1').fetchone()
        database = {'engine': 'SQLite', 'path': str(path), 'table': 'demo_state', 'rowId': 1}
        payload = json.loads(row[0]) if row else {}
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
        from db import get_database_config
        import psycopg2
        connection = psycopg2.connect(**get_database_config())
        try:
            connection.set_session(readonly=True)
            with connection.cursor() as cursor:
                cursor.execute('SELECT payload FROM sportspace_state WHERE id = 1')
                row = cursor.fetchone()
            payload = row[0] if row else {}
        finally:
            connection.close()
        database = {'engine': 'PostgreSQL', 'table': 'sportspace_state', 'rowId': 1}
    if not isinstance(payload, dict):
        raise ValueError('The saved app state is not a JSON object')
    return database, payload


def project(item, fields):
    return {field: item.get(field) for field in fields}


def report(database, payload, tournament_id=None, player_id=None, include_details=False):
    service = payload.get('organisationService', {})
    tournaments = service.get('tournaments', [])
    registrations = service.get('registrations', [])
    players = payload.get('arena', {}).get('players', [])
    tournament_fields = ('id', 'name', 'status', 'organisationId', 'publishedAt')
    registration_fields = ('id', 'tournamentId', 'playerId', 'teamName', 'status')
    if include_details:
        tournament_fields += ('description', 'format', 'formatDetails', 'teamSize', 'entryFee',
                              'prize', 'eligibility', 'rules', 'contact', 'onlinePlatform',
                              'customDetails', 'registrationQuestions')
        registration_fields += ('answers', 'notes')
    result = {
        'database': database,
        'counts': {
            'tournaments': len(tournaments),
            'registrations': len(registrations),
            'registeredAccounts': len(payload.get('accounts', {})),
        },
        'tournaments': [
            {**project(item, tournament_fields),
             'visibleToPlayers': bool(item.get('publishedAt'))}
            for item in tournaments if not tournament_id or item.get('id') == tournament_id
        ],
        'registrations': [
            project(item, registration_fields)
            for item in registrations
            if (not tournament_id or item.get('tournamentId') == tournament_id)
            and (not player_id or item.get('playerId') == player_id)
        ],
    }
    if player_id:
        result['playerProfiles'] = [
            project(item, ('id', 'name', 'sport', 'city', 'state', 'country', 'bio', 'photoPrivacy'))
            for item in players if item.get('id') == player_id
        ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sqlite', default=os.environ.get('SPORTSPACE_SOCIAL_DB'),
                        help='Existing SQLite database; otherwise read PostgreSQL using DB_* variables')
    parser.add_argument('--tournament-id', help='Only show this tournament and its registrations')
    parser.add_argument('--player-id', help='Show this profile and only this player\'s registrations')
    parser.add_argument('--include-details', action='store_true',
                        help='Include tournament options and private registration answers and notes')
    arguments = parser.parse_args()
    try:
        database, payload = read_state(arguments.sqlite)
        result = report(database, payload, arguments.tournament_id, arguments.player_id,
                        arguments.include_details)
    except ValueError as error:
        parser.exit(1, f'{error}\n')
    except Exception as error:
        parser.exit(1, f'Could not read app state ({type(error).__name__}). '
                       'Check the database settings and use the app virtual environment.\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
