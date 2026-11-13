#!/bin/bash
# upload.sh <workdir> <cluster> <run_id> <set>  (gpadmin) -- make sure the set's result is in the report DB, whatever happened:
#  1. proteus uploaded itself (report_id.log exists) -> keep it
#     else -> fallback: build overview.log from rollout_sql.log, run proteus' result_analyzer + upload_logs on a staged copy
#  2. fill host metric curves from sysmon (no Prometheus needed)
#  3. copy tpc-bench extras (run.json, summary, plans, qmon/sysmon, version, show all, ...) to /proteus/perf/<id>/tpcbench/
set -uo pipefail
W=$1; NAME=$2; RID=$3; S=$4
C=$W/clusters/$NAME; R=$C/runs/$RID; O=$R/$S; P=$W/proteus; TS=tpc-$S
set +u; source $C/cluster.env; set -u
log(){ echo "[$(date '+%F %T')] upload $S: $*"; }
CFG=$(cat $O/config_name 2>/dev/null) || { log "no config_name, nothing to upload"; exit 1; }
read t0 t1 prc < $O/window.txt
KEY=$P/tools/report_key; chmod 600 $KEY 2>/dev/null
source $W/bin/site.env    # TPCBENCH_REPORT_SSH / _WEB / _DIR (site config, copied by nightly.py)
RID_FILE=$O/proteus_results/logs/report_id.log
if [ ! -s $RID_FILE ]; then
  log "proteus did not upload (rc=$prc) -> fallback analyzer"
  STG=$R/upload_$S; rm -rf $STG; mkdir -p $STG/results/default_stream/$CFG/intermediates
  ln -sfn $P/configs $STG/configs; ln -sfn $P/analyzers $STG/analyzers; ln -sfn $P/common $STG/common; ln -sfn $P/tools $STG/tools
  cp -a $O/proteus_results/logs $STG/results/default_stream/$CFG/logs 2>/dev/null || mkdir -p $STG/results/default_stream/$CFG/logs/$TS
  L=$STG/results/default_stream/$CFG/logs/$TS; mkdir -p $L
  [ -f $L/status ] || echo FAILURE > $L/status
  grep -q SUCCESS $L/status || echo FAILURE > $L/status
  if [ ! -s $L/overview.log ]; then
    awk -F'|' '{split($4,t,":"); d=t[1]*3600+t[2]*60+t[3]; if($3!="-1"){q+=d;ok++} else bad++}
      END{print "LOAD_TIME=0"; print "QUERIES_TIME=" q+0; print "SUCCESS_QUERY=" ok+0; print "FAILD_QUERY=" bad+0}' $L/rollout_sql.log 2>/dev/null > $L/overview.log
  fi
  (
    set -a; source $C/proteus_env.conf; source $P/configs/$CFG/test.conf; set +a
    export PROTEUS_DIR=$STG CONFIG=$CFG STREAM_ID=default_stream TEST_SETS=$TS RUN_SQL=true OUTPUT_TO_REPORT_DB=true SYS_METRICS=false
    export LOG_DIR=$STG/results/default_stream/$CFG/logs
    export DB_VERSION="$(psql -Atc 'select version()' 2>/dev/null || cat $R/version.txt)"
    export DB_PRODUCT_NAME="$(cd $P && python3 analyzers/get_db_product_name.py "$DB_VERSION")" BUILT_AT="$(cd $P && python3 analyzers/get_built_at.py "$DB_VERSION")"
    export TEST_DURATION=$(( (t1 - t0) / 60 )) PYTHONPATH=$STG:$W/pylib:${PYTHONPATH:-}
    cd $STG/analyzers && python3 result_analyzer.py $t0 $t1
    cd $STG && REPORT_ID=$(cat $LOG_DIR/report_id.log) bash tools/upload_logs.sh
  ) > $O/upload_fallback.log 2>&1
  cp $STG/results/default_stream/$CFG/logs/report_id.log $RID_FILE 2>/dev/null
fi
id=$(cat $RID_FILE 2>/dev/null)
[ -n "$id" ] || { log "ERROR no report id (see $O/upload_fallback.log)"; exit 2; }
for sf in $R/sysmon.tsv $R/sysmon.*.tsv; do      # every host of the cluster, labelled with its IP
  h=
  [ -f $sf ] || continue
  hb=$R/host_before.json; [ $sf != $R/sysmon.tsv ] && { h=${sf#$R/sysmon.}; h=${h%.tsv}; hb=$R/host_before.$h.json; }
  ip=$(python3 -c "import json;print(json.load(open('$hb'))['ip'])" 2>/dev/null || getent hosts ${h:-x} | awk '{print $1}')
  python3 $W/bin/upload_metrics.py $sf $id $t0 $t1 "$ip" 2>&1 | tail -1
done
T=$R/extras_$S.tgz
( cd $R && tar czf $T --ignore-failed-read $S/run.json $S/summary.txt $S/plans $S/queries $S/inject.log $S/crash_evidence.txt $S/explain_pass.log \
    sysmon.tsv qmon.jsonl $(cd $R && ls sysmon.*.tsv qmon.*.jsonl host_before.*.json 2>/dev/null) $S/layout.txt \
    version.txt show_all.txt host_before.json layout.txt release-info.yaml build.json cluster.json run.log state.json 2>/dev/null )
RD=$TPCBENCH_REPORT_DIR
ssh -o StrictHostKeyChecking=no -o BatchMode=yes -i $KEY $TPCBENCH_REPORT_SSH "mkdir -p $RD/$id/tpcbench" \
 && scp -q -o StrictHostKeyChecking=no -i $KEY $T $TPCBENCH_REPORT_SSH:$RD/$id/tpcbench/ \
 && ssh -o BatchMode=yes -i $KEY $TPCBENCH_REPORT_SSH "cd $RD/$id/tpcbench && tar xzf $(basename $T) && rm $(basename $T) && chmod -R g+w ." \
 && log "extras uploaded to $RD/$id/tpcbench" || log "WARNING extras upload failed"
echo $id > $O/uploaded
log "OK report $TPCBENCH_REPORT_WEB/$id"
