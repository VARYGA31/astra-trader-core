import os
ALLOWED_ASSETS=("BTC","ETH","GRAM")
STATE_DIR=os.getenv("STATE_DIR","/data")
INITIAL_EQUITY=float(os.getenv("INITIAL_EQUITY","100"))
MAX_DRAWDOWN_PCT=float(os.getenv("MAX_DRAWDOWN_PCT","0.25"))
MAX_OPEN_POSITIONS=int(os.getenv("MAX_OPEN_POSITIONS","2"))
