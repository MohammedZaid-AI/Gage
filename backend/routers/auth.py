"""Farmer authentication: register, login, current farmer."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.security import create_access_token, hash_password, verify_password
from backend.database import get_db
from backend.dependencies import get_current_farmer
from backend.models import Farmer
from backend.schemas import FarmerOut, LoginRequest, RegisterRequest, TokenOut

logger = logging.getLogger("gage.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)) -> TokenOut:
    if db.execute(select(Farmer).where(Farmer.phone == req.phone)).scalar_one_or_none():
        raise HTTPException(409, "Phone already registered")
    farmer = Farmer(
        phone=req.phone,
        password_hash=hash_password(req.password),
        name=req.name,
        language=req.language or "kn",
    )
    db.add(farmer)
    db.commit()
    db.refresh(farmer)
    logger.info("farmer %d registered", farmer.id)
    return TokenOut(access_token=create_access_token(farmer.id))


@router.post("/login", response_model=TokenOut)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> TokenOut:
    farmer = db.execute(
        select(Farmer).where(Farmer.phone == req.phone)
    ).scalar_one_or_none()
    if not farmer or not verify_password(req.password, farmer.password_hash):
        raise HTTPException(401, "Invalid phone or password")
    return TokenOut(access_token=create_access_token(farmer.id))


@router.get("/me", response_model=FarmerOut)
def me(farmer: Farmer = Depends(get_current_farmer)) -> Farmer:
    return farmer
