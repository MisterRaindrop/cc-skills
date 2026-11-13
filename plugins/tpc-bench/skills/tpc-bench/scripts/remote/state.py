#!/usr/bin/env python3
"""state.py <state.json> set k1 v1 [k2 v2 ...] | get  -- tiny progress file read by the skill while it polls."""
import json, os, sys, time
p = sys.argv[1]
s = json.load(open(p)) if os.path.exists(p) else {}
if sys.argv[2] == "set":
    kv = sys.argv[3:]
    s.update(dict(zip(kv[::2], kv[1::2]))); s["updated_at"] = time.strftime("%F %T")
    tmp = p + ".tmp"; json.dump(s, open(tmp, "w"), indent=1); os.replace(tmp, p)
else:
    print(json.dumps(s, indent=1, ensure_ascii=False))
