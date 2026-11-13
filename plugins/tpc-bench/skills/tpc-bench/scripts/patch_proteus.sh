#!/bin/bash
# patch_proteus.sh <proteus_dir> -- idempotent local patches applied to the tpc-bench copy of proteus (recorded in .tpcbench_patches):
#  1. gpfdist is started via `ssh host "bash -c './start_gpfdist.sh ...'"`: the remote shell has no GPHOME unless the
#     user's ~/.bashrc sets one (we never edit it) -> pass GPHOME explicitly.
#  2. stop_gpfdist.sh kills EVERY gpfdist on the host (other users' too) -> only kill gpfdist serving tpcbench_ dirs.
#  3. 01_gen_data runs `ssh host "pkill dbgen"` / `pkill dsdgen` on every segment host as gpadmin (same uid as gpadmin
#     in docker containers) -> only kill generators whose command line has a tpcbench_ path (dbgen runs from the
#     segment dir, dsdgen gets -dir <segment dir>). The [d] keeps the remote shell from matching its own command line.
#  4. get_gpfdist_port picks <digit>4660 (ds) / <digit>5880 (h) from the segment port's first digit, i.e. the same
#     ports as nearly every other proteus user on the host -> honour TPCBENCH_GPFDIST_PORT (load.sh picks a free base).
#  5. 07_multi_user waits until no stream is left by counting `ps | grep psql | grep multi_user` (tpc-h) or every
#     "07_multi_user/test.sh" of the gpadmin uid (tpc-ds) -- other users' proteus runs (same uid in containers) would
#     keep our run waiting / end it early -> count only processes under OUR proteus directory.
set -euo pipefail
P=$1
for s in tpc-h tpc-ds; do
  r=$P/testsets/$s/04_load/rollout.sh
  grep -q 'GPHOME=${GPHOME} ./start_gpfdist.sh' $r || sed -i 's#\./start_gpfdist\.sh#GPHOME=${GPHOME} ./start_gpfdist.sh#g' $r
  k=$P/testsets/$s/04_load/stop_gpfdist.sh
  grep -q 'grep tpcbench_' $k || sed -i 's#ps -ef | grep gpfdist |#ps -ef | grep gpfdist | grep tpcbench_ |#' $k
  grep -q 'grep tpcbench_' $k || { echo "patch 2 failed on $k"; exit 1; }
  g=$P/testsets/$s/01_gen_data/rollout.sh
  sed -i 's#ssh ${i} "pkill dbgen"#ssh ${i} "pkill -f '"'"'tpcbench_.*[d]bgen'"'"'"#; s#ssh ${i} "pkill dsdgen"#ssh ${i} "pkill -f '"'"'[d]sdgen.*tpcbench_'"'"'"#' $g
  grep -qE '"pkill (dbgen|dsdgen)"' $g && { echo "patch 3 failed on $g"; exit 1; }
  f=$P/testsets/$s/functions.sh
  grep -q TPCBENCH_GPFDIST_PORT $f || sed -i 's#^function get_gpfdist_port() {#function get_gpfdist_port() {\n  if [ -n "${TPCBENCH_GPFDIST_PORT:-}" ]; then GPFDIST_PORT=${TPCBENCH_GPFDIST_PORT}; export GPFDIST_PORT; return; fi#' $f
  grep -q TPCBENCH_GPFDIST_PORT $f || { echo "patch 4 failed on $f"; exit 1; }
  m=$P/testsets/$s/07_multi_user/rollout.sh
  sed -i 's#grep psql | grep multi_user | grep -v grep#grep psql | grep -F "${PWD}/" | grep -v grep#; s#grep "07_multi_user/test.sh"#grep -F "${PWD}/test.sh"#' $m
  grep -qE 'grep multi_user \||grep "07_multi_user/test.sh"' $m && { echo "patch 5 failed on $m"; exit 1; }
done
printf "gphome-for-gpfdist\nstop-only-tpcbench-gpfdist\npkill-only-tpcbench-generators\ngpfdist-port-override\nmulti-user-count-own-only\n" > $P/.tpcbench_patches
echo "proteus patched"
