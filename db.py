import sqlite3

conn = sqlite3.connect("database.db")
c = conn.cursor()

# ---------------- Users table ----------------
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT,
    email TEXT UNIQUE,
    mobile TEXT,
    coindcx_id TEXT,
    password TEXT
)
""")

# ---------------- Broker credentials linked to user ----------------
c.execute("""
CREATE TABLE IF NOT EXISTS broker_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    api_key TEXT,
    secret TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
)
""")

# ---------------- Watchlist per user ----------------
c.execute("""
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    symbol TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
)
""")

# ---------------- User trade history ----------------
c.execute("""
CREATE TABLE IF NOT EXISTS trade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER,
    symbol TEXT,
    direction TEXT,          -- LONG / SHORT
    strategy TEXT,
    status TEXT,             -- OPEN / CLOSED
    qty REAL,
    entry_price REAL,
    leverage INTEGER,
    entry_time DATETIME,
    close_price REAL,
    close_time DATETIME,
    exit_reason TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
)
""")

# ---------------- Strategy master table ----------------
c.execute("""
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    description TEXT
)
""")

# ---------------- User strategy configuration ----------------
c.execute("""
CREATE TABLE IF NOT EXISTS user_strategy_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    symbol TEXT,
    strategy_id INTEGER,
    leverage INTEGER,
    margin REAL,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(strategy_id) REFERENCES strategies(id)
)
""")

# ---------------- Strategy signals ----------------
c.execute("""
CREATE TABLE IF NOT EXISTS strategy_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER,
    symbol TEXT,
    direction TEXT,          -- LONG / SHORT
    status TEXT,             -- ACTIVE / EXITED
    entry_price REAL,
    entry_time DATETIME,
    exit_price REAL,
    exit_time DATETIME,
    gain_ratio REAL,
    FOREIGN KEY(strategy_id) REFERENCES strategies(id)
)
""")

conn.commit()
conn.close()

print("✅ Database initialized with users, broker_credentials, watchlist, trade_history, strategies, user_strategy_config, strategy_signals")
