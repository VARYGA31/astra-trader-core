#!/usr/bin/env python3
import time
from decimal import Decimal, ROUND_DOWN
from pybit.unified_trading import HTTP

import config
from asset_map import ASSETS

class BybitTestnetAdapter:
    def __init__(self):
        if not config.BYBIT_API_KEY or not config.BYBIT_API_SECRET:
            raise RuntimeError("BYBIT_TESTNET_CREDENTIALS_MISSING")
        self.session = HTTP(
            testnet=True,
            api_key=config.BYBIT_API_KEY,
            api_secret=config.BYBIT_API_SECRET,
        )
        self.category = config.BYBIT_CATEGORY

    def symbol(self, asset):
        if asset not in ASSETS:
            raise RuntimeError("TRADE_NOT_ALLOWED")
        return ASSETS[asset]["bybit_linear"]

    def instrument(self, asset):
        symbol=self.symbol(asset)
        r=self.session.get_instruments_info(category=self.category, symbol=symbol)
        rows=r.get("result",{}).get("list",[])
        if not rows:
            raise RuntimeError(f"BYBIT_SYMBOL_UNAVAILABLE:{symbol}")
        x=rows[0]
        if x.get("status") not in {"Trading","PreLaunch"}:
            raise RuntimeError(f"BYBIT_SYMBOL_NOT_TRADING:{symbol}:{x.get('status')}")
        return x

    def ticker(self, asset):
        symbol=self.symbol(asset)
        r=self.session.get_tickers(category=self.category, symbol=symbol)
        rows=r.get("result",{}).get("list",[])
        if not rows:
            raise RuntimeError("BYBIT_TICKER_EMPTY")
        return float(rows[0]["lastPrice"])

    def _floor_step(self, value, step):
        value=Decimal(str(value)); step=Decimal(str(step))
        return (value/step).to_integral_value(rounding=ROUND_DOWN)*step

    def qty_for_notional(self, asset, notional_usd):
        info=self.instrument(asset)
        price=Decimal(str(self.ticker(asset)))
        lot=info["lotSizeFilter"]
        step=Decimal(str(lot["qtyStep"]))
        min_qty=Decimal(str(lot.get("minOrderQty","0")))
        min_notional=Decimal(str(lot.get("minNotionalValue","0")))
        qty=self._floor_step(Decimal(str(notional_usd))/price, step)
        if qty < min_qty:
            raise RuntimeError(f"BYBIT_QTY_BELOW_MIN:{qty}<{min_qty}")
        if min_notional and qty*price < min_notional:
            raise RuntimeError(f"BYBIT_NOTIONAL_BELOW_MIN:{qty*price}<{min_notional}")
        return format(qty, "f")

    def set_leverage(self, asset, leverage):
        symbol=self.symbol(asset)
        lev=str(leverage)
        try:
            return self.session.set_leverage(
                category=self.category,
                symbol=symbol,
                buyLeverage=lev,
                sellLeverage=lev,
            )
        except Exception as e:
            # Bybit can reject a no-op leverage change; verify current position config later.
            if "not modified" in str(e).lower():
                return {"retCode":0,"retMsg":"leverage not modified"}
            raise

    def get_position(self, asset):
        symbol=self.symbol(asset)
        r=self.session.get_positions(category=self.category, symbol=symbol)
        rows=r.get("result",{}).get("list",[])
        if not rows:
            return None
        # In one-way mode there should be one row.
        row=rows[0]
        size=float(row.get("size") or 0)
        if size <= 0:
            return None
        return row

    def wait_position(self, asset, timeout=12):
        deadline=time.time()+timeout
        while time.time()<deadline:
            p=self.get_position(asset)
            if p:
                return p
            time.sleep(0.8)
        return None

    def open_market(self, asset, action, notional_usd, leverage, stop_loss):
        symbol=self.symbol(asset)
        self.instrument(asset)  # availability check
        self.set_leverage(asset, leverage)
        qty=self.qty_for_notional(asset, notional_usd)
        side="Buy" if action=="LONG" else "Sell"
        r=self.session.place_order(
            category=self.category,
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
            positionIdx=config.BYBIT_POSITION_IDX,
        )
        order_id=r.get("result",{}).get("orderId")
        p=self.wait_position(asset)
        if not p:
            raise RuntimeError(f"BYBIT_POSITION_NOT_VISIBLE_AFTER_ORDER:{order_id}")
        # Exchange-side hard stop survives app/model outages.
        self.session.set_trading_stop(
            category=self.category,
            symbol=symbol,
            tpslMode="Full",
            positionIdx=config.BYBIT_POSITION_IDX,
            stopLoss=str(stop_loss),
            slTriggerBy="MarkPrice",
        )
        return {
            "order_id":order_id,
            "symbol":symbol,
            "side":action,
            "qty":float(p.get("size") or qty),
            "entry":float(p.get("avgPrice") or 0),
            "leverage":float(p.get("leverage") or leverage),
            "position_value":float(p.get("positionValue") or 0),
        }

    def close_market(self, asset, side, qty):
        symbol=self.symbol(asset)
        close_side="Sell" if side=="LONG" else "Buy"
        return self.session.place_order(
            category=self.category,
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty=str(qty),
            reduceOnly=True,
            positionIdx=config.BYBIT_POSITION_IDX,
        )

    def latest_closed_pnl(self, asset):
        symbol=self.symbol(asset)
        r=self.session.get_closed_pnl(category=self.category, symbol=symbol, limit=1)
        rows=r.get("result",{}).get("list",[])
        return rows[0] if rows else None

    def wallet_balance(self):
        return self.session.get_wallet_balance(accountType="UNIFIED")
