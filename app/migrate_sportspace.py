"""Import the existing local SQLite demo once, without replacing PostgreSQL data."""
import json
import sqlite3
import sys
from pathlib import Path
from db import sportspace_state
from social import seed
from arena import ensure_arena

source = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/sportspace-social.sqlite3')
def initial():
    if source.exists():
        connection = sqlite3.connect(f'file:{source}?mode=ro', uri=True)
        try:
            row = connection.execute('SELECT payload FROM demo_state WHERE id = 1').fetchone()
            if row:
                return json.loads(row[0])
        finally:
            connection.close()
    return seed()

if __name__ == '__main__':
    with sportspace_state(initial) as data:
        arena = ensure_arena(data)
        print(f"PostgreSQL ready: {len(arena['players'])} players, {len(data['posts'])} posts")
