#!/usr/bin/env bash
# Usage: grader/run_and_push.sh "<commit title, or empty to use the command's first line of output>" "<command>"
#
# Used by the workflows that change participants.csv. Runs the command on the latest main, commits what it
# changed and pushes. If someone else pushed first, it starts again from their version, so two changes made
# at the same time both land and neither works from an out-of-date file.
set -euo pipefail
title=$1
command=$2
summary=${GITHUB_STEP_SUMMARY:-/dev/null}
attempt_summary=$(mktemp)

git config user.name "leaderboard-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

for attempt in 1 2 3 4 5; do
  git fetch -q origin main
  git reset -q --hard origin/main
  : > "$attempt_summary"
  # A failing command (for example a misspelled name) stops here: nothing is committed.
  if ! output=$(GITHUB_STEP_SUMMARY=$attempt_summary bash -c "$command"); then
    cat "$attempt_summary" >> "$summary"
    exit 1
  fi
  echo "$output"
  for f in participants.csv grader/results.json grader/history.json; do
    if [[ -e $f ]]; then git add "$f"; fi
  done
  if git diff --cached --quiet; then
    cat "$attempt_summary" >> "$summary"
    echo "Nothing changed."
    exit 0
  fi
  git commit -q -m "${title:-Leaderboard: $(head -1 <<< "$output")}" -m "By @${GITHUB_ACTOR:-unknown}."
  if git push -q origin HEAD:main; then
    cat "$attempt_summary" >> "$summary"
    exit 0
  fi
  echo "Someone else changed the leaderboard at the same time; redoing this on top of their change." >&2
  sleep $((attempt * 3))
done
echo "Could not save after 5 attempts. Run the action again." >&2
exit 1
