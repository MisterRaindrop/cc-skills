#!/bin/bash
# deep.sh <W> <cluster> <deep.py args...>   (gpadmin) -- wrapper: cluster env, then deep.py (see its docstring)
W=$1; NAME=$2; shift 2
set +u; source $W/clusters/$NAME/cluster.env; set -u
export TERM=xterm
exec python3 $W/bin/deep.py "$@"
