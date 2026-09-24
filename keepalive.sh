#!/usr/bin/env bash
# Docker Desktop's Resource Saver stops the Linux VM after a few minutes of
# container inactivity, which takes the Kong data plane down mid-demo. A cheap
# periodic request keeps the VM warm for the length of a session.
while true; do
  curl -s -o /dev/null --max-time 3 http://localhost:8000/ 2>/dev/null
  sleep 30
done
