#!/usr/bin/env python3
from pathlib import Path
import json, py_compile

bad_null=[]
bad_syntax={}
for p in Path(".").glob("*.py"):
    b=p.read_bytes()
    if b"\x00" in b:
        bad_null.append(p.name)
        continue
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception as e:
        bad_syntax[p.name]=str(e)

status="OK" if not bad_null and not bad_syntax else "FAILED"
print(json.dumps({
    "status":status,
    "null_byte_files":bad_null,
    "syntax_errors":bad_syntax,
    "will_open_order":False,
    "will_close_order":False,
    "will_call_model":False
},ensure_ascii=False,indent=2))
raise SystemExit(0 if status=="OK" else 1)
