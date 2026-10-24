#!/usr/bin/env python3
import json

import config
from okx_demo_adapter import OKXDemoAdapter, OKXHTTPError


class FakeResponse:
    def __init__(self,status_code,text,payload=None):
        self.status_code=status_code
        self.text=text
        self._payload=payload
    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_private_http_error_includes_exchange_code_and_path():
    a=object.__new__(OKXDemoAdapter)
    response=FakeResponse(
        401,
        '{"code":"50111","msg":"Invalid OK-ACCESS-KEY"}',
        {"code":"50111","msg":"Invalid OK-ACCESS-KEY"},
    )
    try:
        a._raise_private_http_error(response,"POST","/api/v5/trade/order")
        raise AssertionError("expected OKXHTTPError")
    except OKXHTTPError as e:
        s=str(e)
        assert "status=401" in s,s
        assert "method=POST" in s,s
        assert "path=/api/v5/trade/order" in s,s
        assert "api_code=50111" in s,s
        assert "Invalid OK-ACCESS-KEY" in s,s


def test_credentials_are_redacted_from_http_body():
    old_key=config.OKX_API_KEY
    old_secret=config.OKX_API_SECRET
    old_pass=config.OKX_API_PASSPHRASE
    try:
        config.OKX_API_KEY="KEY_SHOULD_NOT_LEAK"
        config.OKX_API_SECRET="SECRET_SHOULD_NOT_LEAK"
        config.OKX_API_PASSPHRASE="PASS_SHOULD_NOT_LEAK"
        a=object.__new__(OKXDemoAdapter)
        body="KEY_SHOULD_NOT_LEAK SECRET_SHOULD_NOT_LEAK PASS_SHOULD_NOT_LEAK"
        response=FakeResponse(401,body,{"code":"1","msg":"auth failed"})
        try:
            a._raise_private_http_error(response,"POST","/api/v5/trade/order")
            raise AssertionError("expected OKXHTTPError")
        except OKXHTTPError as e:
            s=str(e)
            assert "KEY_SHOULD_NOT_LEAK" not in s,s
            assert "SECRET_SHOULD_NOT_LEAK" not in s,s
            assert "PASS_SHOULD_NOT_LEAK" not in s,s
            assert s.count("[REDACTED]")>=3,s
    finally:
        config.OKX_API_KEY=old_key
        config.OKX_API_SECRET=old_secret
        config.OKX_API_PASSPHRASE=old_pass


if __name__=="__main__":
    test_private_http_error_includes_exchange_code_and_path()
    test_credentials_are_redacted_from_http_body()
    print(json.dumps({
        "status":"OK",
        "will_open_order":False,
        "will_close_order":False,
        "will_call_model":False,
        "sanitized_okx_http_diagnostics":"OK",
    },indent=2))
