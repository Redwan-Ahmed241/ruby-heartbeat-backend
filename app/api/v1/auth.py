"""Authentication router: /api/v1/auth."""
from datetime import timedelta, date
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
from app.core.enums import UserRole, UserStatus, BloodGroup
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

    # Determine role (defaults to DONOR for regular users)
    target_role = request_data.role or UserRole.DONOR

    # Create base user
    new_user = User(
        full_name=request_data.full_name,
        email=request_data.email,
        phone=request_data.phone,
        password_hash=hash_password(request_data.password),
        role=target_role,
        status=UserStatus.ACTIVE,
        nid_or_birth_cert=request_data.nid_or_birth_cert,
        date_of_birth=request_data.date_of_birth,
    )
    db.add(new_user)
    db.flush()

    # Atomically provision role profiles
    if target_role == UserRole.HOSPITAL_ADMIN:
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

    elif target_role == UserRole.SYSTEM_ADMIN:
        # System Administrator account does not require donor/recipient capability records
        pass

    else:
        # Unified regular user (Zero-DDL Dual Capability: Donor + Recipient)
        dp = request_data.donor_profile
        rp = request_data.recipient_profile

        # 1. Resolve & create Donor profile
        donor_blood_group = (
            dp.blood_group if dp and dp.blood_group
            else request_data.blood_group or BloodGroup.O_POSITIVE
        )
        donor_dob = request_data.date_of_birth or (dp.date_of_birth if dp and dp.date_of_birth else date(2000, 1, 1))
        donor_gender = (
            dp.gender if dp and dp.gender
            else request_data.gender or "Other"
        )
        donor_weight = (
            dp.weight if dp and dp.weight
            else request_data.weight or 65.0
        )
        donor_address = (
            dp.address if dp and dp.address
            else request_data.address
            or (rp.address if rp and rp.address else "Dhaka, Bangladesh")
        )
        donor_lat = (
            dp.latitude if dp and dp.latitude is not None
            else request_data.latitude if request_data.latitude is not None else 23.8103
        )
        donor_lng = (
            dp.longitude if dp and dp.longitude is not None
            else request_data.longitude if request_data.longitude is not None else 90.4125
        )

        donor_age = request_data.age if request_data.age is not None else (dp.age if dp and dp.age is not None else None)
        if donor_age is not None and not (dp and dp.date_of_birth) and not request_data.date_of_birth:
            today = date.today()
            donor_dob = date(today.year - donor_age, today.month, min(today.day, 28))
        elif donor_age is None and donor_dob:
            today = date.today()
            donor_age = today.year - donor_dob.year - ((today.month, today.day) < (donor_dob.month, donor_dob.day))

        donor = Donor(
            donor_id=new_user.user_id,
            blood_group=donor_blood_group,
            date_of_birth=donor_dob,
            age=donor_age,
            gender=donor_gender,
            weight=donor_weight,
            address=donor_address,
            latitude=donor_lat,
            longitude=donor_lng,
        )
        db.add(donor)
        db.flush()

        # Initial medical info for donor capability
        medical_info = MedicalInfo(
            donor_id=donor.donor_id,
            hemoglobin_level=(dp.hemoglobin_level if dp and dp.hemoglobin_level else 13.0),
            chronic_diseases=(dp.chronic_diseases if dp else None),
            medications=(dp.medications if dp else None),
            allergies=(dp.allergies if dp else None),
            other_notes=(dp.other_notes if dp else None),
        )
        db.add(medical_info)

        # 2. Resolve & create Recipient profile
        recipient_nid = (
            rp.nid_passport_no if rp and rp.nid_passport_no
            else request_data.nid_passport_no or "N/A"
        )
        recipient_address = (
            rp.address if rp and rp.address
            else donor_address
        )
        recipient_rel = (
            rp.relationship_to_patient if rp and rp.relationship_to_patient
            else "Self"
        )
        recipient_patient = (
            rp.patient_name if rp and rp.patient_name
            else new_user.full_name
        )

        recipient = Recipient(
            recipient_id=new_user.user_id,
            nid_passport_no=recipient_nid,
            address=recipient_address,
            relationship_to_patient=recipient_rel,
            patient_name=recipient_patient,
        )
        db.add(recipient)

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
