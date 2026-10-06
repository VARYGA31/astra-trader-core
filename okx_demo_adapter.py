#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

import requests

import config
from asset_map import ASSETS

class OKXAPIError(RuntimeError):
    pass

class OKXDemoAdapter:
    def __init__(self):
        if not config.OKX_API_KEY or not config.OKX_API_SECRET or not config.OKX_API_PASSPHRASE:
            raise RuntimeError("OKX_DEMO_CREDENTIALS_MISSING")
        self.base = config.OKX_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({"User-Agent":"ASTRA-Trader-OKX-Demo/1.0"})

    def inst_id(self, asset):
        if asset not in ASSETS:
            raise RuntimeError("TRADE_NOT_ALLOWED")
        return ASSETS[asset]["okx_swap"]

    def _timestamp(self):
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")

    def _signed_headers(self, method, request_path, body=""):
        ts = self._timestamp()
        prehash = ts + method.upper() + request_path + body
        sign = base64.b64encode(
            hmac.new(
                config.OKX_API_SECRET.encode(),
                prehash.encode(),
                hashlib.sha256
            ).digest()
        ).decode()
        return {
            "Content-Type":"application/json",
            "OK-ACCESS-KEY":config.OKX_API_KEY,
            "OK-ACCESS-SIGN":sign,
            "OK-ACCESS-TIMESTAMP":ts,
            "OK-ACCESS-PASSPHRASE":config.OKX_API_PASSPHRASE,
            "x-simulated-trading":"1",
        }

    def _check(self, data):
        if str(data.get("code")) != "0":
            raise OKXAPIError(f"OKX_ERROR code={data.get('code')} msg={data.get('msg')} data={data.get('data')}")
        return data

    def private_get(self, path, params=None):
        qs = urlencode(params or {})
        request_path = path + (("?" + qs) if qs else "")
        headers = self._signed_headers("GET", request_path, "")
        r = self.session.get(self.base + request_path, headers=headers, timeout=15)
        r.raise_for_status()
        return self._check(r.json())

    def private_post(self, path, payload):
        body = json.dumps(payload, separators=(",",":"))
        headers = self._signed_headers("POST", path, body)
        r = self.session.post(self.base + path, data=body, headers=headers, timeout=15)
        r.raise_for_status()
        return self._check(r.json())

    def public_get(self, path, params=None):
        r = self.session.get(
            self.base + path,
            params=params or {},
            headers={"x-simulated-trading":"1"},
            timeout=15,
        )
        r.raise_for_status()
        return self._check(r.json())

    def balance(self):
        return self.private_get("/api/v5/account/balance")

    def account_config(self):
        return self.private_get("/api/v5/account/config")

    def ensure_net_mode(self):
        cfg = self.account_config().get("data", [])
        mode = cfg[0].get("posMode") if cfg else None
        if mode == "net_mode":
            return {"status":"OK","posMode":mode}
        # Demo only: set net mode before first trade. OKX will reject if positions/orders prevent it.
        result = self.private_post("/api/v5/account/set-position-mode", {"posMode":"net_mode"})
        return {"status":"CHANGED","posMode":"net_mode","result":result}

    def instrument(self, asset):
        inst = self.inst_id(asset)
        data = self.public_get("/api/v5/public/instruments", {"instType":"SWAP","instId":inst}).get("data", [])
        if not data:
            raise RuntimeError(f"OKX_INSTRUMENT_UNAVAILABLE:{inst}")
        x = data[0]
        if x.get("state") != "live":
            raise RuntimeError(f"OKX_INSTRUMENT_NOT_LIVE:{inst}:{x.get('state')}")
        return x

    def ticker(self, asset):
        inst = self.inst_id(asset)
        data = self.public_get("/api/v5/market/ticker", {"instId":inst}).get("data", [])
        if not data:
            raise RuntimeError(f"OKX_TICKER_EMPTY:{inst}")
        return float(data[0]["last"])

    @staticmethod
    def _floor_step(value, step):
        value = Decimal(str(value))
        step = Decimal(str(step))
        return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

    def contracts_for_notional(self, asset, notional_usd):
        info = self.instrument(asset)
        px = Decimal(str(self.ticker(asset)))
        ct_val = Decimal(str(info.get("ctVal") or "1"))
        ct_ccy = str(info.get("ctValCcy") or "")
        base_ccy = self.inst_id(asset).split("-")[0]
        lot = Decimal(str(info["lotSz"]))
        min_sz = Decimal(str(info["minSz"]))

        if ct_ccy == base_ccy:
            usd_per_contract = ct_val * px
        elif ct_ccy in {"USD","USDT","USDC"}:
            usd_per_contract = ct_val
        else:
            raise RuntimeError(f"OKX_UNSUPPORTED_CONTRACT_VALUE_CCY:{ct_ccy}")

        raw = Decimal(str(notional_usd)) / usd_per_contract
        qty = self._floor_step(raw, lot)
        if qty < min_sz:
            min_notional = min_sz * usd_per_contract
            raise RuntimeError(
                f"OKX_NOTIONAL_BELOW_MIN requested={notional_usd} "
                f"minimum_approx={min_notional} inst={info['instId']}"
            )
        return format(qty, "f"), float(usd_per_contract)

    def normalize_qty(self, asset, qty):
        info = self.instrument(asset)
        lot = Decimal(str(info["lotSz"]))
        min_sz = Decimal(str(info["minSz"]))
        q = self._floor_step(Decimal(str(qty)), lot)
        if q < min_sz:
            raise RuntimeError(f"OKX_QTY_BELOW_MIN:{q}<{min_sz}")
        return format(q, "f")

    def set_leverage(self, asset, leverage):
        return self.private_post("/api/v5/account/set-leverage", {
            "instId": self.inst_id(asset),
            "lever": str(leverage),
            "mgnMode": config.OKX_TD_MODE,
        })

    def order_details(self, asset, ord_id):
        return self.private_get("/api/v5/trade/order", {
            "instId": self.inst_id(asset),
            "ordId": ord_id,
        })

    def wait_filled(self, asset, ord_id, timeout=15):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            d = self.order_details(asset, ord_id).get("data", [])
            if d:
                last = d[0]
                if last.get("state") == "filled":
                    return last
                if last.get("state") in {"canceled","mmp_canceled"}:
                    raise RuntimeError(f"OKX_ORDER_TERMINAL:{last}")
            time.sleep(0.8)
        return last

    def open_market(self, asset, action, notional_usd, leverage, stop_loss):
        self.ensure_net_mode()
        self.set_leverage(asset, leverage)
        qty, usd_per_contract = self.contracts_for_notional(asset, notional_usd)
        side = "buy" if action == "LONG" else "sell"
        payload = {
            "instId": self.inst_id(asset),
            "tdMode": config.OKX_TD_MODE,
            "side": side,
            "ordType": "market",
            "sz": qty,
            "attachAlgoOrds": [{
                "slTriggerPx": str(stop_loss),
                "slTriggerPxType": "mark",
                "slOrdPx": "-1",
            }],
        }
        r = self.private_post("/api/v5/trade/order", payload)
        row = r.get("data", [])[0]
        if row.get("sCode") not in (None, "", "0"):
            raise RuntimeError(f"OKX_ORDER_REJECTED:{row}")
        ord_id = row.get("ordId")
        fill = self.wait_filled(asset, ord_id)
        avg_px = float((fill or {}).get("avgPx") or self.ticker(asset))
        fill_sz = float((fill or {}).get("accFillSz") or qty)
        actual_notional = fill_sz * usd_per_contract
        return {
            "order_id": ord_id,
            "inst_id": self.inst_id(asset),
            "side": action,
            "qty_contracts": fill_sz,
            "entry": avg_px,
            "leverage": float(leverage),
            "position_value_usd_approx": actual_notional,
        }

    def positions(self, asset=None):
        params = {"instId": self.inst_id(asset)} if asset else {}
        return self.private_get("/api/v5/account/positions", params).get("data", [])

    def get_position(self, asset):
        for p in self.positions(asset):
            try:
                qty = float(p.get("pos") or 0)
            except Exception:
                qty = 0
            if abs(qty) > 0:
                return p
        return None

    def close_market(self, asset, side, qty_contracts):
        qty = self.normalize_qty(asset, qty_contracts)
        close_side = "sell" if side == "LONG" else "buy"
        return self.private_post("/api/v5/trade/order", {
            "instId": self.inst_id(asset),
            "tdMode": config.OKX_TD_MODE,
            "side": close_side,
            "ordType": "market",
            "sz": qty,
            "reduceOnly": True,
        })

    def latest_position_history(self, asset):
        data = self.private_get("/api/v5/account/positions-history", {
            "instType":"SWAP",
            "instId":self.inst_id(asset),
            "limit":"10",
        }).get("data", [])
        return data[0] if data else None
