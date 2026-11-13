#!/bin/bash
# inject_cancel.sh <proteus run.log> <query file id e.g. 105>  -- flow test only: wait until proteus starts that query,
# (matches the '[ts] psql ... -f .../<id>.*.sql' execution line, not qgen's echo of file names),
# then pg_cancel_backend() every active client backend of this cluster after 2s (proteus runs one query at a time),
# so the run must report exactly one failed query and carry on.
LOG=$1; QID=$2
for i in $(seq 1 14400); do grep -qE "\] psql .* -f [^ ]*/$QID\.[^ ]+\.sql" "$LOG" 2>/dev/null && break; sleep 0.5; done
sleep 2
psql -d gpadmin -Atc "select now(), pid, pg_cancel_backend(pid), left(regexp_replace(query,'\s+',' ','g'),80)
  from pg_stat_activity where state='active' and pid<>pg_backend_pid() and backend_type='client backend'"
echo "injected cancel for query file $QID"
