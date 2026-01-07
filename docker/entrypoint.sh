#!/bin/sh
# Ghillie container entrypoint
#
# This script sets up signal handling for graceful shutdown and executes
# the command passed as arguments. Designed for use in Kubernetes where
# SIGTERM is sent during pod termination.
#
# Usage:
#   ghillie-entrypoint python -m ghillie.runtime
#   ghillie-entrypoint [command] [args...]

set -e

# Forward SIGTERM and SIGINT to the child process for graceful shutdown
trap 'kill -TERM $child_pid 2>/dev/null' TERM INT

# Execute the command passed as arguments
exec "$@" &
child_pid=$!

# Wait for the child process to complete
wait $child_pid
exit_code=$?

# Return the child's exit code
exit $exit_code
