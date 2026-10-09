# ============================================================
# db.py  –  PostgreSQL connection pool + helper utilities
# ============================================================
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import pandas as pd
import warnings
warnings.filterwarnings('ignore', message='.*SQLAlchemy.*')
warnings.filterwarnings('ignore', category=UserWarning, module='pandas')
import logging
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Connection pool (min 1, max 10 connections)
# ------------------------------------------------------------------
_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=30,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=10,
        )
    return _pool


def get_conn():
    """Borrow a connection from the pool."""
    return get_pool().getconn()


def release_conn(conn):
    """Return a connection to the pool."""
    get_pool().putconn(conn)


# ------------------------------------------------------------------
# Context manager for safe usage
# ------------------------------------------------------------------
class DBConn:
    def __enter__(self):
        self.conn = get_conn()
        self.conn.autocommit = False
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        release_conn(self.conn)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def execute(sql: str, params=None):
    """Run INSERT / UPDATE / DELETE."""
    with DBConn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())


def executemany(sql: str, param_list: list):
    """Bulk INSERT / UPDATE."""
    with DBConn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, sql, param_list)


def fetchall(sql: str, params=None) -> list:
    """Return list of dicts."""
    with DBConn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return [dict(r) for r in cur.fetchall()]


def fetchone(sql: str, params=None) -> dict:
    """Return single row as dict, or None."""
    with DBConn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
            return dict(row) if row else None


def query_df(sql: str, params=None) -> pd.DataFrame:
    """Return query result as a pandas DataFrame."""
    with DBConn() as conn:
        with conn.cursor() as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)


def test_connection() -> bool:
    try:
        row = fetchone("SELECT 1 AS ok")
        return row and row.get("ok") == 1
    except Exception as e:
        logger.error(f"DB connection test failed: {e}")
        return False
