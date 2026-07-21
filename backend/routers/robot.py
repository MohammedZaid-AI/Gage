"""Robot movement commands. For now they log + broadcast; ESP32 hook goes in `_dispatch`."""
import logging

from fastapi import APIRouter

from backend.models import _now
from backend.realtime import broadcaster
from backend.schemas import RobotCommandResponse
from backend.state import robot_state

logger = logging.getLogger("gage.robot")
router = APIRouter(prefix="/robot", tags=["robot"])


async def _dispatch(command: str) -> RobotCommandResponse:
    # ponytail: ESP32 transport (serial/MQTT/HTTP) plugs in right here.
    logger.info("robot command: %s", command)
    robot_state["last_command"] = command
    robot_state["last_command_at"] = _now().isoformat()
    await broadcaster.broadcast("robot", dict(robot_state))
    return RobotCommandResponse(command=command)


@router.post("/forward", response_model=RobotCommandResponse)
async def forward() -> RobotCommandResponse:
    return await _dispatch("forward")


@router.post("/backward", response_model=RobotCommandResponse)
async def backward() -> RobotCommandResponse:
    return await _dispatch("backward")


@router.post("/left", response_model=RobotCommandResponse)
async def left() -> RobotCommandResponse:
    return await _dispatch("left")


@router.post("/right", response_model=RobotCommandResponse)
async def right() -> RobotCommandResponse:
    return await _dispatch("right")


@router.post("/stop", response_model=RobotCommandResponse)
async def stop() -> RobotCommandResponse:
    return await _dispatch("stop")
