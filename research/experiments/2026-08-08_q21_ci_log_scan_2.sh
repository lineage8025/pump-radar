#!/bin/bash
for id in 31149734820 31154624475 31162130742 31169353892 31176534420 31196565434 31205492907 31214134947 31222189508 31228449577 31236291196 31239708989 31242962642; do
  jid=$(gh api repos/lineage8025/pump-radar/actions/runs/$id/jobs -q '.jobs[0].id' 2>/dev/null)
  if [ -z "$jid" ]; then echo "$id: no job"; continue; fi
  log=$(gh api repos/lineage8025/pump-radar/actions/jobs/$jid/logs 2>/dev/null)
  result=$(echo "$log" | grep -A6 '"type": "result"' | tr -d '\n')
  echo "$id job=$jid :: $result"
done
