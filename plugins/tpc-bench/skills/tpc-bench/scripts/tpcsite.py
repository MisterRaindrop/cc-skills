"""Site configuration: ~/.tpc-bench/site.env (KEY=VALUE, see site.env.example in the skill). Keeps hosts, keys and
paths of one installation out of the skill."""
import os

PATH = os.path.expanduser(os.environ.get("TPCBENCH_SITE", "~/.tpc-bench/site.env"))


def load():
    d = {}
    if os.path.exists(PATH):
        for l in open(PATH):
            l = l.split("#", 1)[0].strip() if not l.lstrip().startswith("TPCBENCH_REPORT_DB") else l.strip()
            if "=" in l and not l.startswith("#"):
                k, v = l.split("=", 1)
                d[k.strip()] = v.strip()
    d.update({k: v for k, v in os.environ.items() if k.startswith("TPCBENCH_")})
    return d


C = load()


def get(k, default=None):
    v = C.get(k, default)
    if v is None:
        raise SystemExit(f"{k} is not set: copy site.env.example to {PATH} and fill it in")
    return v
