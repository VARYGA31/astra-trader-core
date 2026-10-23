#!/usr/bin/env python3
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config
import mtf_gate
import observability


def _frame(trend="BULLISH", structure="BULLISH", momentum="BULLISH", close=101.0, volume=1.0, bar=0.5):
    return {
        "status":"OK",
        "close":close,
        "indicators":{"ema20":100.0,"ema50":99.0,"rsi14":55.0,"atr_pct":1.0},
        "regimes":{"trend":trend,"structure":structure,"momentum":momentum},
        "structure":{"breakout_up":structure=="BULLISH","breakout_down":structure=="BEARISH"},
        "changes_pct":{"1bar":bar},
        "volume":{"ratio_to_avg20":volume},
        "last_confirmed_close_time_ms":123456,
    }


def _package(frames):
    return {
        "asset":"BTC",
        "decision_context":{"market":{"multi_timeframe":{"status":"OK","frames":frames}}},
    }


def test_volume_veto_is_explicit():
    frames={
        "4h":_frame(),
        "1h":_frame(),
        "15m":_frame(volume=0.20),
    }
    x=mtf_gate.evaluate(_package(frames))
    assert x["passed"] is False,x
    assert "15M_VOLUME_VETO" in x["blockers"],x
    assert x["primary_blocker"]=="15M_VOLUME_VETO",x
    best=max(x["candidates"],key=lambda c:c["quality"])
    assert best["trigger_15m"]["count"]>=config.MTF_TRIGGER_MIN_COMPONENTS,best
    assert best["trigger_15m"]["confirmed"] is False,best


def test_regime_and_quality_are_explicit():
    frames={
        "4h":_frame(trend="BEARISH",structure="BEARISH",momentum="BEARISH",close=98.0,bar=-0.5),
        "1h":_frame(),
        "15m":_frame(),
    }
    x=mtf_gate.evaluate(_package(frames))
    assert x["passed"] is False,x
    assert "4H_REGIME_NOT_ALIGNED" in x["blockers"],x
    assert "MTF_QUALITY_BELOW_MIN" in x["blockers"],x


def test_shadow_replay_scores_blocked_direction_without_trading():
    old_shadow=observability.SHADOW
    old_outcomes=observability.SHADOW_OUTCOMES
    old_enabled=config.MTF_SHADOW_REPLAY_ENABLED
    old_horizons=config.MTF_SHADOW_REPLAY_HORIZONS_MINUTES
    old_batch=config.MTF_SHADOW_REPLAY_EVAL_BATCH
    try:
        with tempfile.TemporaryDirectory() as td:
            observability.SHADOW=Path(td)/"shadow.jsonl"
            observability.SHADOW_OUTCOMES=Path(td)/"outcomes.jsonl"
            config.MTF_SHADOW_REPLAY_ENABLED=True
            config.MTF_SHADOW_REPLAY_HORIZONS_MINUTES=(60,)
            config.MTF_SHADOW_REPLAY_EVAL_BATCH=10

            now=datetime.now(timezone.utc)
            setup={
                "timestamp_utc":(now-timedelta(minutes=70)).isoformat(),
                "setup_id":"s1",
                "asset":"BTC",
                "price":100.0,
                "direction":"LONG",
                "quality":80.0,
                "blocked_reason":"MTF_NOT_ALIGNED",
                "mtf_primary_blocker":"15M_VOLUME_VETO",
                "mtf_blockers":["15M_VOLUME_VETO"],
            }
            observability.SHADOW.write_text(json.dumps(setup)+"\n",encoding="utf-8")
            package={
                "asset":"BTC",
                "decision_context":{"market":{
                    "generated_at_utc":now.isoformat(),
                    "perp_okx":{"last_price":102.0},
                    "spot":{"price":102.0},
                }},
            }
            result=observability._evaluate_mtf_shadow_outcomes(package,"BTC")
            assert result["status"]=="OK" and result["evaluated"]==1,result
            rows=observability._load_jsonl(observability.SHADOW_OUTCOMES)
            assert len(rows)==1,rows
            assert rows[0]["signed_return_pct"]==2.0,rows[0]
            summary=observability.shadow_replay_summary(168)
            assert summary["by_horizon"]["60"]["samples"]==1,summary
            assert summary["by_primary_blocker"]["15M_VOLUME_VETO"]["avg_signed_return_pct"]==2.0,summary
    finally:
        observability.SHADOW=old_shadow
        observability.SHADOW_OUTCOMES=old_outcomes
        config.MTF_SHADOW_REPLAY_ENABLED=old_enabled
        config.MTF_SHADOW_REPLAY_HORIZONS_MINUTES=old_horizons
        config.MTF_SHADOW_REPLAY_EVAL_BATCH=old_batch


if __name__=="__main__":
    test_volume_veto_is_explicit()
    test_regime_and_quality_are_explicit()
    test_shadow_replay_scores_blocked_direction_without_trading()
    print(json.dumps({
        "status":"OK",
        "will_open_order":False,
        "will_close_order":False,
        "will_call_model":False,
        "mtf_explainability":"OK",
        "shadow_replay":"OK",
    },indent=2))
