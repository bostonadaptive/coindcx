from typing import List, Optional
from pydantic import BaseModel


class StrategySignalItem(BaseModel):
    config_id: int
    user_id: int
    strategy: Optional[str]
    symbol: Optional[str]
    generated_signal: Optional[str]
    type: Optional[str]
    status: Optional[str]
    entry_price: Optional[float]
    exit_price: Optional[float]
    entry_time: Optional[str]
    exit_time: Optional[str]
    trading_status: Optional[str]
    exit_reason: Optional[str]
    is_paper: bool


class StrategySignalsResponse(BaseModel):
    page: int
    per_page: int
    total_setups: int
    items: List[StrategySignalItem]


class ProfileResponse(BaseModel):
    user_id: int
    has_credentials: bool
    total_trades: int
    profitable: int
    losses: int
    accuracy: float
    net_pnl: float


class RefillWalletResponse(BaseModel):
    success: bool
    balance: float
    realized_pnl: Optional[float]
    unrealized_pnl: Optional[float]
    available_balance: Optional[float]


class BalanceResponse(BaseModel):
    connected: bool
    balance: Optional[float]
    locked: Optional[float]
    currency: Optional[str]


class WatchlistItem(BaseModel):
    symbol: str
    label: str
    ltp: Optional[float]


class PositionItem(BaseModel):
    id: str
    pair: str
    side: str
    qty: str
    entry_px: str
    mark_px: Optional[str]
    lev: str


class PositionsResponse(BaseModel):
    positions: List[PositionItem]
