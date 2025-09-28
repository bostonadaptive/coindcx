import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, SIGNAL_CACHE, _redis, redis_get_signal
from model import db, UserStrategySetup, StrategySignal, PaperTrade, Strategy

with app.app_context():
    user_id = 1
    setups = db.session.query(UserStrategySetup).filter_by(user_id=user_id).all()
    print('found setups:', len(setups))
    for us in setups:
        print('\n--- setup', us.id, 'symbol=', us.symbol, 'strategy_id=', us.strategy_id)
        strat = db.session.get(Strategy, us.strategy_id) if us and us.strategy_id else None
        print('strategy name:', strat.name if strat else None)
        # try to fetch StrategySignal similar to API
        sig = StrategySignal.query.filter(StrategySignal.strategy_id == us.strategy_id, StrategySignal.symbol == us.symbol).order_by(StrategySignal.entry_time.desc()).first()
        if not sig:
            sig = StrategySignal.query.filter(StrategySignal.strategy_id == us.strategy_id, StrategySignal.symbol.ilike(f"%{(us.symbol or '').replace('BINANCE:','').replace('B-','').replace('_','')}%") ).order_by(StrategySignal.entry_time.desc()).first()
        if not sig:
            sig = StrategySignal.query.filter_by(strategy_id=us.strategy_id).order_by(StrategySignal.entry_time.desc()).first()
        print('sig:', sig and {'id': sig.id, 'entry_price': sig.entry_price, 'exit_price': sig.exit_price, 'entry_time': sig.entry_time, 'exit_time': sig.exit_time, 'direction': sig.direction, 'status': sig.status} or None)
        pt = PaperTrade.query.filter_by(user_id=us.user_id, config_id=us.id).order_by(PaperTrade.exit_time.desc(), PaperTrade.entry_time.desc()).first()
        if not pt:
            pt = PaperTrade.query.filter_by(user_id=us.user_id, symbol=us.symbol).order_by(PaperTrade.exit_time.desc(), PaperTrade.entry_time.desc()).first()
        print('pt:', pt and {'id': pt.id, 'entry_price': pt.entry_price, 'exit_price': pt.exit_price, 'entry_time': pt.entry_time, 'exit_time': pt.exit_time, 'status': pt.status, 'exit_reason': getattr(pt,'exit_reason',None)} or None)
        # cached
        try:
            cached = redis_get_signal(us.id) if _redis else None
        except Exception:
            cached = None
        if not cached:
            cached = SIGNAL_CACHE.get(us.id)
        print('cached:', cached)
        # build record like API
        def map_direction(s,p):
            if s and getattr(s,'direction',None): return s.direction
            if p and getattr(p,'side',None): return p.side
            return None
        def map_status(s,p):
            if s and getattr(s,'status',None): return s.status
            if p and getattr(p,'status',None): return p.status
            return None
        record = {'config_id': us.id, 'user_id': us.user_id, 'strategy': (strat.name if strat else (str(us.strategy_id) if us.strategy_id else 'Unknown')), 'symbol': us.symbol, 'generated_signal': None, 'type': map_direction(sig, pt), 'status': map_status(sig, pt)}
        print('record start:', record)
        # fill prices
        if pt:
            try:
                if getattr(pt,'entry_price',None) is not None:
                    record['entry_price'] = float(pt.entry_price)
                if getattr(pt,'exit_price',None) is not None:
                    record['exit_price'] = float(pt.exit_price)
            except Exception:
                pass
        print('record after pt prices:', record)
        if cached:
            record['generated_signal'] = cached.get('signal') or cached.get('last_signal')
            if (record.get('type') in (None,'')) and (record.get('status') in (None,'')):
                sigv = cached.get('signal') or cached.get('last_signal')
                if sigv:
                    record['type'] = sigv
                    record['trading_status'] = sigv
        print('final record:', record)
