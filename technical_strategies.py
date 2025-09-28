# technical_strategies.py

from typing import List, Dict, Any
import numpy as np
import pandas as pd
import math

# If you use 'ta' library, import it
import ta

def intraday_strategy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    required_cols = ['close', 'open', 'high', 'low', 'volume']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in input DataFrame: {missing}")

    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    df['ema21'] = ta.trend.EMAIndicator(df['close'], window=21).ema_indicator()
    df['ema50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
    macd = ta.trend.MACD(df['close'], window_fast=12, window_slow=26, window_sign=9)
    df['macd_line'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()

    df['buy_signal'] = (
        (df['rsi'] > 35) &
        (df['ema21'] > df['ema50']) &
        (df['macd_line'].shift(1) < df['macd_signal'].shift(1)) &
        (df['macd_line'] > df['macd_signal'])
    )

    # Optionally df['sell_signal'] if needed
    return df

def scalping_strategy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['ema9'] = ta.trend.EMAIndicator(df['close'], window=9).ema_indicator()
    df['ema21'] = ta.trend.EMAIndicator(df['close'], window=21).ema_indicator()

    # VWAP: need volume; if your df has volume, else approximate
    # ta library has VWAPIndicator
    if 'volume' in df.columns:
        df['vwap'] = ta.volume.VolumeWeightedAveragePrice(
            high=df['high'], low=df['low'], close=df['close'], volume=df['volume'], window=14
        ).volume_weighted_average_price()
    else:
        df['vwap'] = np.nan

    stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'], window=14, smooth_window=3)
    df['stoch_k'] = stoch.stoch()
    df['stoch_d'] = stoch.stoch_signal()

    df['buy_signal'] = (
        (df['close'] > df['vwap']) &
        (df['ema9'] > df['ema21']) &
        (df['stoch_k'].shift(1) < df['stoch_d'].shift(1)) &
        (df['stoch_k'] > df['stoch_d'])
    )
    return df

def swing_strategy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['bb_lower'] = bb.bollinger_lband()
    df['ema50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()

    df['buy_signal'] = (
        (df['rsi'] < 40) &
        (df['close'] <= df['bb_lower']) &
        (df['close'] > df['ema50'])
    )
    return df

def short_term_strategy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['ema21'] = ta.trend.EMAIndicator(df['close'], window=21).ema_indicator()
    df['ema50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
    df['ema100'] = ta.trend.EMAIndicator(df['close'], window=100).ema_indicator()
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    macd = ta.trend.MACD(df['close'], window_fast=12, window_slow=26, window_sign=9)
    df['macd_line'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()

    df['buy_signal'] = (
        (df['ema21'] > df['ema50']) &
        (df['ema50'] > df['ema100']) &
        (df['rsi'] < 70) &
        (df['macd_line'].shift(1) < df['macd_signal'].shift(1)) &
        (df['macd_line'] > df['macd_signal'])
    )
    return df

def long_term_strategy(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['ema50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
    df['ema200'] = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator()
    macd = ta.trend.MACD(df['close'], window_fast=12, window_slow=26, window_sign=9)
    df['macd_line'] = macd.macd()

    df['buy_signal'] = (
        (df['ema50'] > df['ema200']) &
        (df['macd_line'] > 0)
    )
    return df

def trend_speed_analyzer_strategy(df: pd.DataFrame, max_length: int = 50, accel_multiplier: float = 5.0, 
                                 lookback_period: int = 100, collen: int = 100) -> pd.DataFrame:
    """
    Implementation of the Trend Speed Analyzer strategy based on PineScript logic.
    
    Args:
        df: DataFrame with OHLCV data
        max_length: Maximum length for dynamic moving average
        accel_multiplier: Accelerator multiplier for dynamic EMA
        lookback_period: Period for trend analysis
        collen: Collection period for trend visualization
        
    Returns:
        DataFrame with buy/sell signals
    """
    df = df.copy()
    required_cols = ['close', 'open', 'high', 'low']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in input DataFrame: {missing}")
    
    # Dynamic Average calculation
    df['counts_diff'] = df['close']
    df['max_abs_counts_diff'] = df['counts_diff'].abs().rolling(window=200).max()
    df['counts_diff_norm'] = (df['counts_diff'] + df['max_abs_counts_diff']) / (2 * df['max_abs_counts_diff'])
    df['dyn_length'] = 5 + df['counts_diff_norm'] * (max_length - 5)
    
    # Calculate accelerator factor
    df['delta_counts_diff'] = df['counts_diff'].diff().abs()
    df['max_delta_counts_diff'] = df['delta_counts_diff'].rolling(window=200).max()
    df['max_delta_counts_diff'] = df['max_delta_counts_diff'].replace(0, 1)  # Avoid division by zero
    df['accel_factor'] = df['delta_counts_diff'] / df['max_delta_counts_diff']
    
    # Adjust alpha with accelerator factor
    df['alpha_base'] = 2 / (df['dyn_length'] + 1)
    df['alpha'] = df['alpha_base'] * (1 + df['accel_factor'] * accel_multiplier)
    df['alpha'] = df['alpha'].clip(upper=1)  # Ensure alpha does not exceed 1
    
    # Compute dynamic EMA
    df['dyn_ema'] = np.nan
    
    # Initialize first value
    df.loc[df.index[0], 'dyn_ema'] = df.loc[df.index[0], 'close']
    
    # Calculate dynamic EMA
    for i in range(1, len(df)):
        alpha = df.loc[df.index[i], 'alpha']
        close = df.loc[df.index[i], 'close']
        prev_ema = df.loc[df.index[i-1], 'dyn_ema']
        df.loc[df.index[i], 'dyn_ema'] = alpha * close + (1 - alpha) * prev_ema
    
    # Trend Speed calculation
    df['trend'] = df['dyn_ema']
    df['c'] = df['close'].rolling(window=10).mean()  # RMA approximation
    df['o'] = df['open'].rolling(window=10).mean()   # RMA approximation
    
    # Initialize speed
    df['speed'] = 0.0
    df['speed'] = df['c'] - df['o']
    
    # Calculate trend speed
    for i in range(1, len(df)):
        df.loc[df.index[i], 'speed'] = df.loc[df.index[i-1], 'speed'] + df.loc[df.index[i], 'c'] - df.loc[df.index[i], 'o']
    
    # Calculate HMA for trend speed
    df['trendspeed'] = ta.trend.wma_indicator(df['speed'], window=5)  # Approximation of HMA
    
    # Calculate normalized speed for visualization
    df['min_speed'] = df['speed'].rolling(window=collen).min()
    df['max_speed'] = df['speed'].rolling(window=collen).max()
    df['normalized_speed'] = (df['speed'] - df['min_speed']) / (df['max_speed'] - df['min_speed'])
    
    # Generate buy/sell signals
    df['buy_signal'] = (
        (df['speed'] > 0) & 
        (df['speed'].shift(1) <= 0) &
        (df['dyn_ema'] > df['dyn_ema'].shift(1))
    )
    
    df['sell_signal'] = (
        (df['speed'] < 0) & 
        (df['speed'].shift(1) >= 0) &
        (df['dyn_ema'] < df['dyn_ema'].shift(1))
    )
    
    return df


def twin_range_filter_strategy(df: pd.DataFrame, source_col: str = 'close', per1: int = 27, mult1: float = 1.6,
                               per2: int = 55, mult2: float = 2.0) -> pd.DataFrame:
    """
    Port of 'Twin Range Filter' PineScript -> Pandas. Produces buy/sell signals
    via columns 'buy_signal' and 'sell_signal'.
    """
    df = df.copy()
    if source_col not in df.columns:
        raise ValueError(f"Source column '{source_col}' missing from DataFrame")

    src = df[source_col].astype(float)

    def smoothrng(x: pd.Series, t: int, m: float) -> pd.Series:
        wper = t * 2 - 1
        avrng = x.diff().abs().ewm(span=t, adjust=False).mean()
        smr = avrng.ewm(span=wper, adjust=False).mean() * m
        return smr

    smrng1 = smoothrng(src, per1, mult1)
    smrng2 = smoothrng(src, per2, mult2)
    smrng = (smrng1 + smrng2) / 2.0

    # range filter logic
    filt = pd.Series(index=df.index, dtype=float)
    # initialize filt[0] = src[0]
    if len(src) > 0:
        filt.iloc[0] = src.iloc[0]
    for i in range(1, len(src)):
        x = src.iloc[i]
        prev = filt.iloc[i-1]
        r = smrng.iloc[i] if not pd.isna(smrng.iloc[i]) else smrng.iloc[i-1] if i-1>=0 else 0.0
        # translate the nested ternary logic from Pine
        if x > prev:
            if (x - r) < prev:
                filt.iloc[i] = prev
            else:
                filt.iloc[i] = x - r
        else:
            if (x + r) > prev:
                filt.iloc[i] = prev
            else:
                filt.iloc[i] = x + r

    # upward / downward counts
    upward = (filt > filt.shift(1)).astype(int).groupby((filt <= filt.shift(1)).cumsum()).cumcount()+1
    downward = (filt < filt.shift(1)).astype(int).groupby((filt >= filt.shift(1)).cumsum()).cumcount()+1
    # fill zeros where not increasing/decreasing
    upward = upward.where(filt > filt.shift(1), 0)
    downward = downward.where(filt < filt.shift(1), 0)

    hband = filt + smrng
    lband = filt - smrng

    # long/short conditions
    src_prev = src.shift(1)
    longCond = ((src > filt) & (src > src_prev) & (upward > 0)) | ((src > filt) & (src < src_prev) & (upward > 0))
    shortCond = ((src < filt) & (src < src_prev) & (downward > 0)) | ((src < filt) & (src > src_prev) & (downward > 0))

    # CondIni: carry previous state (0 -> neutral, 1 -> long, -1 -> short)
    condini = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        if longCond.iloc[i]:
            condini.iloc[i] = 1
        elif shortCond.iloc[i]:
            condini.iloc[i] = -1
        else:
            condini.iloc[i] = condini.iloc[i-1]

    # Entry logic: flip when current cond and previous CondIni opposite
    long_entries = (longCond) & (condini.shift(1) == -1)
    short_entries = (shortCond) & (condini.shift(1) == 1)

    df['filt'] = filt
    df['hband'] = hband
    df['lband'] = lband
    df['buy_signal'] = long_entries.fillna(False)
    df['sell_signal'] = short_entries.fillna(False)
    return df


def ai_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """AI-style heuristic strategy combining chart-patterns, support/resistance
    and common candlestick patterns. Returns buy/sell signals and optional reasons.
    """
    df = df.copy()
    # Ensure base columns exist
    for col in ('open', 'high', 'low', 'close'):
        if col not in df.columns:
            df[col] = 0.0

    body = (df['close'] - df['open']).abs()
    body_signed = (df['close'] - df['open'])
    upper_shad = df['high'] - df[['open', 'close']].max(axis=1)
    lower_shad = df[['open', 'close']].min(axis=1) - df['low']

    is_hammer = (lower_shad > 2 * body) & (upper_shad < 0.5 * body) & (body / (df['high'] - df['low'] + 1e-9) < 0.4) & (body_signed > 0)
    is_hanging_man = (lower_shad > 2 * body) & (upper_shad < 0.5 * body) & (body / (df['high'] - df['low'] + 1e-9) < 0.4) & (body_signed < 0)
    is_shooting_star = (upper_shad > 2 * body) & (lower_shad < 0.5 * body) & (body / (df['high'] - df['low'] + 1e-9) < 0.4) & (body_signed < 0)

    prev_body_signed = body_signed.shift(1).fillna(0)
    is_bull_engulf = (prev_body_signed < 0) & (body_signed > 0) & (df['open'] < df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
    is_bear_engulf = (prev_body_signed > 0) & (body_signed < 0) & (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))

    win = 20
    rolling_high = df['high'].rolling(window=win, min_periods=3).max()
    rolling_low = df['low'].rolling(window=win, min_periods=3).min()

    near_support = (df['low'] <= rolling_low * 1.01) & (df['low'] >= rolling_low * 0.99)
    near_resistance = (df['high'] >= rolling_high * 0.99) & (df['high'] <= rolling_high * 1.01)

    lows = df['low']
    w_pattern = pd.Series(False, index=df.index)
    for i in range(2, len(df) - 2):
        left = lows.iloc[i - 2:i]
        mid = lows.iloc[i]
        right = lows.iloc[i + 1:i + 3]
        if (mid < left.min()) and (mid < right.min()):
            if abs(left.min() - right.min()) / max(left.min(), right.min(), 1e-9) < 0.03:
                w_pattern.iloc[i] = True

    buy = (is_hammer | is_bull_engulf | w_pattern | (near_support & (body_signed > 0)))
    sell = (is_shooting_star | is_bear_engulf | (near_resistance & (body_signed < 0)) | is_hanging_man)

    entry_reason = pd.Series('', index=df.index)
    exit_reason = pd.Series('', index=df.index)
    entry_reason[is_hammer] = 'hammer'
    entry_reason[is_bull_engulf] = 'bullish_engulfing'
    entry_reason[w_pattern] = 'W_pattern'
    entry_reason[near_support & (body_signed > 0)] = 'support_bounce'

    exit_reason[is_shooting_star] = 'shooting_star'
    exit_reason[is_bear_engulf] = 'bearish_engulfing'
    exit_reason[near_resistance & (body_signed < 0)] = 'resistance_rejection'
    exit_reason[is_hanging_man] = 'hanging_man'

    df['buy_signal'] = buy.fillna(False).astype(bool)
    df['sell_signal'] = sell.fillna(False).astype(bool)
    df['entry_reason'] = entry_reason.replace('', None)
    df['exit_reason'] = exit_reason.replace('', None)

    return df

STRATEGY_MAP: Dict[str, Dict[str, Any]] = {
    "Intraday": {
        "func": intraday_strategy,
        "default_timeframes": ["15m"]
    },
    "Scalping": {
        "func": scalping_strategy,
        "default_timeframes": ["15m"]
    },
    "Swing": {
        "func": swing_strategy,
        "default_timeframes": ["2h", "4h"]
    },
    "Short-Term": {
        "func": short_term_strategy,
        "default_timeframes": ["8h", "1d"]
    },
    "Long-Term": {
        "func": long_term_strategy,
        "default_timeframes": ["1d", "1w"]
    },
    "Trend Speed Analyzer": {
        "func": trend_speed_analyzer_strategy,
        "default_timeframes": ["15m", "1h"]
    }

    ,"Twin Range Filter": {
        "func": twin_range_filter_strategy,
        "default_timeframes": ["15m", "1h"]
    }
    ,"AI": {
        "func": ai_strategy,
        "default_timeframes": ["15m", "1h"]
    }
}
