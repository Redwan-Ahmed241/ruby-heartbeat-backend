"""Authentication router: /api/v1/auth."""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from jwt.exceptions import PyJWTError

from app.core.database import get_db
from app.core.config import settings
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.core.enums import UserRole, UserStatus
from app.models.user import User, Donor, MedicalInfo, Recipient, Hospital
from app.schemas.auth import (
    UserRegisterRequest,
    LoginRequest,
    RefreshRequest,
    Token,
    UserResponse,
)
from app.api.deps import get_current_active_user
from app.services.audit import log_system_action

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(request_data: UserRegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Register a new user and atomically create their role-specific profile."""
    # Check if email is already taken
    existing_user = db.query(User).filter(User.email == request_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )

    # Create base user
    new_user = User(
        full_name=request_data.full_name,
        email=request_data.email,
        phone=request_data.phone,
        password_hash=hash_password(request_data.password),
        role=request_data.role,
        status=UserStatus.ACTIVE,
    )
    db.add(new_user)
    db.flush()

    # Atomically create role child profile
    if request_data.role == UserRole.DONOR:
        if not request_data.donor_profile:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Donor profile data is required for role DONOR.",
            )
        dp = request_data.donor_profile
        donor = Donor(
            donor_id=new_user.user_id,
            blood_group=dp.blood_group,
            date_of_birth=dp.date_of_birth,
            gender=dp.gender,
            weight=dp.weight,
            address=dp.address,
            latitude=dp.latitude,
            longitude=dp.longitude,
        )
        db.add(donor)
        db.flush()

        # Create initial medical info
        medical_info = MedicalInfo(
            donor_id=donor.donor_id,
            hemoglobin_level=dp.hemoglobin_level or 13.0,
            chronic_diseases=dp.chronic_diseases,
            medications=dp.medications,
            allergies=dp.allergies,
            other_notes=dp.other_notes,
        )
        db.add(medical_info)

    elif request_data.role == UserRole.RECIPIENT:
        if not request_data.recipient_profile:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Recipient profile data is required for role RECIPIENT.",
            )
        rp = request_data.recipient_profile
        recipient = Recipient(
            recipient_id=new_user.user_id,
            nid_passport_no=rp.nid_passport_no,
            address=rp.address,
            relationship_to_patient=rp.relationship_to_patient,
            patient_name=rp.patient_name,
        )
        db.add(recipient)

    elif request_data.role == UserRole.HOSPITAL_ADMIN:
        if not request_data.hospital_profile:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Hospital profile data is required for role HOSPITAL_ADMIN.",
            )
        hp = request_data.hospital_profile
        hospital = Hospital(
            user_id=new_user.user_id,
            hospital_name=hp.hospital_name,
            address=hp.address,
            latitude=hp.latitude,
            longitude=hp.longitude,
            contact_number=hp.contact_number,
        )
        db.add(hospital)

    # Log action
    log_system_action(
        db=db,
        action="USER_REGISTERED",
        entity="users",
        entity_id=new_user.user_id,
        user_id=new_user.user_id,
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/login", response_model=Token)
def login(login_data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate user and return access & refresh JWT tokens."""
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User account is {user.status.value}",
        )

    access_token = create_access_token(subject=str(user.user_id), role=user.role.value)
    refresh_token = create_refresh_token(subject=str(user.user_id), role=user.role.value)

    log_system_action(
        db=db,
        action="USER_LOGIN",
        entity="users",
        entity_id=user.user_id,
        user_id=user.user_id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=Token)
def refresh(refresh_data: RefreshRequest, db: Session = Depends(get_db)):
    """Validate refresh token and issue a new token pair."""
    try:
        payload = decode_token(refresh_data.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type for refresh",
            )
        user_id = payload.get("sub")
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user or user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    new_access = create_access_token(subject=str(user.user_id), role=user.role.value)
    new_refresh = create_refresh_token(subject=str(user.user_id), role=user.role.value)

    return Token(
        access_token=new_access,
        refresh_token=new_refresh,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_active_user)):
    """Get authenticated user profile and nested role data."""
    return current_user
