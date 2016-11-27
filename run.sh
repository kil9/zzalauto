#!/bin/bash

N_PIC=10
PORT=5000

case "$1" in
  run)
    N_PIC=${2:-N_PIC}
    curl localhost:${PORT}/run/${N_PIC}
  ;;

  *)
    N_PIC=${1:-N_PIC}
    tmux split-window -v './web.sh'
    tmux split-window -v './worker.sh'
    tmux select-layout main-horizontal
    sleep 5
    curl localhost:${PORT}/run/${N_PIC}
  ;;
esac
