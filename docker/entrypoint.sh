#!/bin/sh
# Ghillie container entrypoint
#
# Executes the command passed as arguments using exec, which replaces this
# shell process with the target command. This allows Kubernetes to deliver
# SIGTERM directly to the main process during pod termination.
#
# Usage:
#   ghillie-entrypoint python -m ghillie.runtime
#   ghillie-entrypoint [command] [args...]

set -e

exec "$@"
