#!/usr/bin/env python3
import argparse,json
import observability

p=argparse.ArgumentParser(description="ASTRA passive analytics report")
p.add_argument("--days",type=float,default=None,help="Optional rolling decision window")
args=p.parse_args()

print(json.dumps(
    observability.analytics_report(days=args.days),
    ensure_ascii=False,
    indent=2,
))
