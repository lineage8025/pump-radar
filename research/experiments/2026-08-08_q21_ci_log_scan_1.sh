#!/bin/bash
for id in 31135718776 31126304726 31122167700 31116450808 31097997600 31082942812 31076303262 31071576762 31059044539 31053065573 31045274333 31037201472 31027795857 30992926040 30984389645 30978412565; do
  jid=$(gh api repos/lineage8025/pump-radar/actions/runs/$id/jobs -q '.jobs[0].id' 2>/dev/null)
  if [ -z "$jid" ]; then echo "$id: no job"; continue; fi
  log=$(gh api repos/lineage8025/pump-radar/actions/jobs/$jid/logs 2>/dev/null)
  result=$(echo "$log" | grep -A6 '"type": "result"' | tr -d '\n')
  created=$(echo "$log" | head -1 | grep -oE '^\S+' )
  echo "$id job=$jid :: $result"
done
