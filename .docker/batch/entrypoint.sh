#!/bin/sh
set -eu

if [ "$#" -eq 0 ]; then
  exec python -u -m app.main
fi

case "$1" in
  ingest|pipeline|cleanup)
    exec python -u -m app.main "$@"
    ;;
  python)
    shift
    exec python -u "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
