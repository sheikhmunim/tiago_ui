#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Start the Tiago Web Interface
# Run from inside the dev container:  bash start.sh
# ─────────────────────────────────────────────────────────────────
set -e

source /opt/ros/noetic/setup.bash

# Always connect to the robot
export ROS_MASTER_URI=http://bandit:11311
export ROS_IP=$(hostname -I | tr ' ' '\n' | grep '^10\.234\.' | head -1)
[ -z "$ROS_IP" ] && export ROS_IP=$(ip route get 10.234.6.53 2>/dev/null | awk '/src/{print $7}' | head -1)
[ -z "$ROS_IP" ] && export ROS_IP=$(hostname -I | awk '{print $1}')
echo "ROS_MASTER_URI : $ROS_MASTER_URI"
echo "ROS_IP         : $ROS_IP"

if ! (echo > /dev/tcp/bandit/22) &>/dev/null 2>&1; then
  echo "⚠ Robot not reachable — rospy will keep retrying until it comes online."
fi

echo ""
echo "Starting FastAPI on 0.0.0.0:8000 ..."
echo "Open:  http://$(hostname -I | awk '{print $1}'):8000"
echo "       http://localhost:8000"
echo ""

cd "$(dirname "$0")/backend"

exec python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level info
