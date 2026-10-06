class LiveTradingDisabledAdapter:
    """Intentional placeholder. Live exchange trading stays disabled during paper validation."""
    def place_order(self,*args,**kwargs): raise RuntimeError("LIVE_TRADING_DISABLED")
    def cancel_order(self,*args,**kwargs): raise RuntimeError("LIVE_TRADING_DISABLED")
