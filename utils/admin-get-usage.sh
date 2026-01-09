#!/bin/bash
# Uses tmux and send-to-claude to fetch quota usage data.
# ClAP-admin function; not to run in a live ClAP install location.
echo "start"
cd /home/clap-admin/cooperation-platform
echo "cd done"
# Load the unified send_to_claude function FIRST so we can use it
source "utils/send_to_claude.sh"
echo "s-t-c sourced"
tmux new -d -s autonomous-claude
echo "tmux made"
sleep 2
tmux send-keys "claude"
sleep 2
tmux send-keys "Enter"
sleep 10
send_to_claude "/usage"
sleep 10
tmux capture-pane -p -S +6 > data/usage_output.txt
send_to_claude "Escape"
sleep 5
send_to_claude "/exit"
tmux kill-session -t autonomous-claude
cat data/usage_output.txt
