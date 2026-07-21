"""Tiny in-memory runtime state (robot telemetry that isn't persisted).

ponytail: single-process dict — fine for one robot + one dashboard at a hackathon.
Move to Redis if you ever run multiple backend workers.
"""
robot_state: dict[str, object] = {
    "online": True,
    "last_command": None,
    "last_command_at": None,
}
