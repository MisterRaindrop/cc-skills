#!/bin/bash
# explain_pass.sh <set_run_dir> -- after the timed run: plain EXPLAIN (no ANALYZE) of every query file, one file each,
# with the run's PRE_QUERY_SQL. finalize.py hashes the plans (plan changed => look at optimizer-side commits first).
O=$1; mkdir -p $O/plans
pre=$(. $TPCBENCH_W/proteus/configs/$(cat $O/config_name)/test.conf >/dev/null 2>&1; echo "$PRE_QUERY_SQL")
for f in $O/queries/*.sql; do
  timeout 300 psql -X -q -P pager=off -v PRE_QUERY_SQL="$pre" -v EXPLAIN_ANALYZE="EXPLAIN" -f $f > $O/plans/$(basename $f .sql).plan 2>&1
done
echo "explained $(ls $O/plans | wc -l) files"
