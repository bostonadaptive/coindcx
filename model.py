from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()

# ----------------- Users -----------------
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    mobile = db.Column(db.String(20))
    password = db.Column(db.String(200), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False, default=1)

    # affiliate system (for moderators)
    referred_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    referrals = db.relationship("User", backref=db.backref("referrer", remote_side=[id]))

    # relationships
    credentials = db.relationship("Credentials", backref="user", uselist=False)
    watchlist = db.relationship("Watchlist", backref="user", lazy=True)
    trade_history = db.relationship("TradeHistory", backref="user", lazy=True)
    strategies = db.relationship("UserStrategyConfig", backref="user", lazy=True)
    # preferred currency for display/export (e.g., 'INR', 'USDT', '$')
    currency = db.Column(db.String(10), default='INR')


# ----------------- Broker Credentials -----------------
class Credentials(db.Model):
    __tablename__ = "credentials"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    email = db.Column(db.String(120))
    mobile = db.Column(db.String(20))
    api_key = db.Column(db.String(200))
    secret_key = db.Column(db.String(200))

    # new fields for CoinDCX user info
    coindcx_id = db.Column(db.String(100))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    # broker reported currency short name (e.g., 'INR', 'USDT')
    currency = db.Column(db.String(10))


# ----------------- Watchlist -----------------
class Watchlist(db.Model):
    __tablename__ = "watchlist"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    symbol = db.Column(db.String(50), nullable=False)


# ----------------- Trade History -----------------
class TradeHistory(db.Model):
    __tablename__ = "trade_history"
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    symbol = db.Column(db.String(50), nullable=False)
    direction = db.Column(db.String(10))  # LONG / SHORT
    strategy = db.Column(db.String(100))
    status = db.Column(db.String(50))  # OPEN / CLOSED
    qty = db.Column(db.Float)
    entry_price = db.Column(db.Float)
    leverage = db.Column(db.Integer)
    entry_time = db.Column(db.DateTime)
    close_price = db.Column(db.Float)
    close_time = db.Column(db.DateTime)
    exit_reason = db.Column(db.String(200))


# ----------------- Strategy -----------------
class Strategy(db.Model):
    __tablename__ = "strategies"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    video_url = db.Column(db.String(255))         # YouTube embed link
    signals = db.Column(db.String(50))            # e.g. "3-4"
    difficulty = db.Column(db.String(50))         # High / Medium / Low
    timeframe = db.Column(db.String(50))          # e.g. "15m"
    gain = db.Column(db.String(50))               # e.g. "+25-45%"
    users = db.Column(db.Integer, default=0)      # how many users
    is_active = db.Column(db.Boolean, default=True)
    
    # Establishing the relationship
    user_strategy_configs = db.relationship('UserStrategyConfig', backref='strategy', lazy=True)


# ----------------- Roles -----------------
class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # admin, moderator, user
    description = db.Column(db.Text)

    users = db.relationship("User", backref="role", lazy=True)


# ----------------- Moderator Earnings -----------------
class ModeratorEarnings(db.Model):
    __tablename__ = "moderator_earnings"
    id = db.Column(db.Integer, primary_key=True)
    moderator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    bonus_amount = db.Column(db.Float, default=0.0)
    bonus_type = db.Column(db.String(50))  # referral_bonus, withdrawal, etc.
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    moderator = db.relationship("User", backref="earnings")


# ----------------- User Strategy Config -----------------
class UserStrategyConfig(db.Model):
    __tablename__ = "user_strategy_config"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    symbol = db.Column(db.String(50), nullable=False)
    strategy_id = db.Column(db.Integer, db.ForeignKey("strategies.id"), nullable=False)
    leverage = db.Column(db.Integer)
    margin = db.Column(db.Float)


# ----------------- User Strategy Setup -----------------
class UserStrategySetup(db.Model):
    __tablename__ = "user_strategy_setup"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    symbol = db.Column(db.String(50), nullable=False)
    strategy_id = db.Column(db.Integer, db.ForeignKey("strategies.id"), nullable=False)
    leverage = db.Column(db.Integer)
    margin = db.Column(db.Float)
    timeframe = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # whether this strategy runs in paper (simulated) mode
    is_paper = db.Column(db.Boolean, default=False)
        
# ----------------- Strategy Signals -----------------
class StrategySignal(db.Model):
    __tablename__ = "strategy_signals"
    id = db.Column(db.Integer, primary_key=True)
    strategy_id = db.Column(db.Integer, db.ForeignKey("strategies.id"), nullable=False)
    symbol = db.Column(db.String(50), nullable=False)
    direction = db.Column(db.String(10))  # LONG / SHORT
    status = db.Column(db.String(50))  # ACTIVE / EXITED
    entry_price = db.Column(db.Float)
    entry_time = db.Column(db.DateTime)
    exit_price = db.Column(db.Float)
    exit_time = db.Column(db.DateTime)
    # human-readable reason for entry/exit (optional)
    entry_reason = db.Column(db.String(200))
    exit_reason = db.Column(db.String(200))
    gain_ratio = db.Column(db.Float)

    strategy = db.relationship("Strategy", backref="strategy_signals")


# ----------------- Backtest Config -----------------
class BacktestConfig(db.Model):
    __tablename__ = "backtest_configs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    strategy_name = db.Column(db.String(100), nullable=False)
    symbol_tv = db.Column(db.String(50), nullable=False)
    pair_market = db.Column(db.String(50), nullable=False)

    margin_in_inr = db.Column(db.Float, default=0.0)
    leverage = db.Column(db.Integer, default=0)
    timeframe = db.Column(db.String(20), nullable=False)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


# ----------------- Backtest Run -----------------
class BacktestRun(db.Model):
    __tablename__ = "backtest_runs"

    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey("backtest_configs.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    status = db.Column(db.String(20), default="pending")  # pending, running, completed, failed
    finished_at = db.Column(db.DateTime)

    trades = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0.0)
    pnl_inr = db.Column(db.Float, default=0.0)
    pnl_usdt = db.Column(db.Float, default=0.0)

    metrics_json = db.Column(db.Text)  # dict: summary stats
    trades_json = db.Column(db.Text)  # list of trades
    equity_json = db.Column(db.Text)  # list of {time, cum_pnl}
    daily_json = db.Column(db.Text)  # dict {day: pnl}
    monthly_json = db.Column(db.Text)  # dict {month: pnl}

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    config = db.relationship("BacktestConfig", backref="runs")
    user = db.relationship("User", backref="backtest_runs")


# ----------------- Paper Wallet -----------------
class PaperWallet(db.Model):
    __tablename__ = 'paper_wallet'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    balance = db.Column(db.Float, default=100000)
    realized_pnl = db.Column(db.Float, default=0)
    unrealized_pnl = db.Column(db.Float, default=0)
    available_balance = db.Column(db.Float, default=100000)

    user = db.relationship("User", backref="paper_wallet")


# ----------------- Paper Trades (simulated) -----------------
class PaperTrade(db.Model):
    __tablename__ = 'paper_trades'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    config_id = db.Column(db.Integer, db.ForeignKey('user_strategy_setup.id'), nullable=True)
    symbol = db.Column(db.String(50), nullable=False)
    tv_symbol = db.Column(db.String(80))
    side = db.Column(db.String(10))  # BUY / SELL
    qty = db.Column(db.Float, default=0.0)
    entry_price = db.Column(db.Float)
    entry_time = db.Column(db.DateTime)
    entry_reason = db.Column(db.String(200))
    exit_price = db.Column(db.Float)
    exit_time = db.Column(db.DateTime)
    exit_reason = db.Column(db.String(200))
    margin = db.Column(db.Float, default=0.0)
    leverage = db.Column(db.Integer, default=1)
    locked_amount = db.Column(db.Float, default=0.0)
    pnl_inr = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='OPEN')  # OPEN / CLOSED
    strategy = db.Column(db.String(100))
    # generated order id for simulated paper trades
    paper_order_id = db.Column(db.String(80), unique=False)

    user = db.relationship('User', backref='paper_trades')
    strategy_setup = db.relationship('UserStrategySetup', backref='paper_trades')


# ----------------- MCP Cache (proxy results persisted) -----------------
class MCPCache(db.Model):
    __tablename__ = 'mcp_cache'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(200), unique=True, nullable=False, index=True)
    value_json = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return { 'key': self.key, 'value_json': self.value_json, 'updated_at': self.updated_at }
