#!/usr/bin/env python3
"""Pure safety test for the shadow crypto lab."""
import inspect,json
import crypto_shadow_lab

src=inspect.getsource(crypto_shadow_lab)
assert crypto_shadow_lab.ORDER_CAPABILITY is False
assert crypto_shadow_lab.MODEL_CALL_CAPABILITY is False
assert "trade_cycle.execute(" not in src
assert "execution_router" not in src
assert "astra_client" not in src
assert "decide(" not in src

print(json.dumps({
    "status":"OK",
    "shadow_only":True,
    "order_capability":False,
    "model_call_capability":False,
},ensure_ascii=False,indent=2))
