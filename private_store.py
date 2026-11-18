"""Private transactional state. Never write orders/PII to the GitHub catalogue.

The singleton row deliberately serializes this small team's stock and order
transactions. PostgreSQL row locking and SQLite BEGIN IMMEDIATE prevent lost
updates across gunicorn workers. A revision guards stale browser edits.
"""
import json
import os
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, Text, select
from sqlalchemy.exc import IntegrityError

metadata = MetaData()
state_table = Table('baron_private_v1', metadata, Column('id', Integer, primary_key=True),
                    Column('payload', Text, nullable=False))
_engines = {}


def engine():
    url = os.environ.get('DATABASE_URL', '')
    if not url:
        if os.environ.get('RENDER'):
            raise ValueError('Configurá DATABASE_URL PostgreSQL para pedidos e inventario persistentes')
        path = Path(__file__).parent / 'instance' / 'baron.sqlite3'
        path.parent.mkdir(exist_ok=True)
        url = 'sqlite:///' + str(path)
    if url.startswith(('postgres://', 'postgresql://')):
        url = 'postgresql+psycopg://' + url.split('://', 1)[1]
    if url not in _engines:
        eng = create_engine(url, pool_pre_ping=True, **({'connect_args': {'timeout': 30}} if url.startswith('sqlite:') else {}))
        metadata.create_all(eng)
        try:
            with eng.begin() as conn:
                conn.execute(state_table.insert().values(id=1, payload=json.dumps({
                    'schema': 1, 'sequence': 0, 'orders': {}, 'lots': {}, 'reservations': [],
                    'movements': [], 'preferences': {}, 'audit': [], 'config': None})))
        except IntegrityError:
            pass  # Another worker initialized the singleton.
        _engines[url] = eng
    return _engines[url]


@contextmanager
def transaction():
    eng = engine()
    with eng.connect() as conn:
        if eng.dialect.name == 'sqlite':
            conn.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            conn.begin()
        try:
            payload = conn.execute(select(state_table.c.payload).where(state_table.c.id == 1).with_for_update()).scalar_one()
            state = json.loads(payload)
            yield state
            conn.execute(state_table.update().where(state_table.c.id == 1).values(payload=json.dumps(state, ensure_ascii=False, allow_nan=False)))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
