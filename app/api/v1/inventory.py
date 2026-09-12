"""Blood inventory and transactions router: /api/v1/inventory."""
from typing import List, Optional
from uuid import UUID
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.enums import (
    UserRole,
    BloodGroup,
    ComponentType,
    TransactionType,
    StockStatus,
)
from app.models.user import User, Hospital
from app.models.inventory import BloodInventory, InventoryTransaction
from app.schemas.inventory import (
    BloodInventoryResponse,
    InventoryTransactionCreate,
    InventoryTransactionResponse,
    ExpiryScanResponse,
)
from app.api.deps import get_current_active_user, RequireRoles
from app.services.inventory import calculate_stock_status, scan_inventory_expiries
from app.services.audit import log_system_action

router = APIRouter(prefix="/inventory", tags=["Blood Inventory"])


@router.get("/", response_model=List[BloodInventoryResponse])
def get_inventory(
    hospital_id: Optional[UUID] = None,
    blood_group: Optional[BloodGroup] = None,
    component_type: Optional[ComponentType] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get current blood inventory across hospital centers with real-time status indicators."""
    query = db.query(BloodInventory)

    # If hospital admin, default to their hospital unless specified
    if current_user.role == UserRole.HOSPITAL_ADMIN:
        hosp = db.query(Hospital).filter(Hospital.user_id == current_user.user_id).first()
        if hosp:
            query = query.filter(BloodInventory.hospital_id == hosp.hospital_id)
    elif hospital_id:
        query = query.filter(BloodInventory.hospital_id == hospital_id)

    if blood_group:
        query = query.filter(BloodInventory.blood_group == blood_group)
    if component_type:
        query = query.filter(BloodInventory.component_type == component_type)

    return query.all()


@router.post("/transaction", response_model=InventoryTransactionResponse, status_code=status.HTTP_201_CREATED)
def record_inventory_transaction(
    tx_data: InventoryTransactionCreate,
    current_user: User = Depends(RequireRoles([UserRole.HOSPITAL_ADMIN, UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """Record stock transaction (IN, OUT, ADJUSTMENT).
    Automatically updates blood_inventory.quantity and recalculates stock status.
    """
    inventory_item = (
        db.query(BloodInventory)
        .filter(BloodInventory.inventory_id == tx_data.inventory_id)
        .first()
    )
    if not inventory_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood inventory record not found.",
        )

    current_qty = float(inventory_item.quantity)
    tx_qty = float(tx_data.quantity)

    # Calculate new quantity based on transaction type
    if tx_data.type == TransactionType.IN:
        new_qty = current_qty + tx_qty
    elif tx_data.type == TransactionType.OUT:
        if current_qty < tx_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient inventory stock (Available: {current_qty}, Requested: {tx_qty}).",
            )
        new_qty = current_qty - tx_qty
    elif tx_data.type == TransactionType.ADJUSTMENT:
        new_qty = tx_qty
    else:
        new_qty = current_qty

    # Update inventory quantity and recalculate status
    inventory_item.quantity = new_qty
    inventory_item.status = calculate_stock_status(new_qty)

    # Create transaction log
    transaction = InventoryTransaction(
        inventory_id=tx_data.inventory_id,
        type=tx_data.type,
        quantity=tx_qty,
        reference_type=tx_data.reference_type,
        reference_id=tx_data.reference_id,
        created_by=current_user.user_id,
    )
    db.add(transaction)

    log_system_action(
        db=db,
        action=f"INVENTORY_TRANSACTION_{tx_data.type.value}",
        entity="blood_inventory",
        entity_id=inventory_item.inventory_id,
        user_id=current_user.user_id,
    )

    db.commit()
    db.refresh(transaction)
    return transaction


@router.post("/scan-expiries", response_model=ExpiryScanResponse)
def trigger_expiry_scan(
    current_user: User = Depends(RequireRoles([UserRole.HOSPITAL_ADMIN, UserRole.SYSTEM_ADMIN])),
    db: Session = Depends(get_db),
):
    """Triggers 72-hour expiry monitor sweep across inventory units."""
    scanned_count, expiring_count, expiring_items = scan_inventory_expiries(db=db, hours=72)

    log_system_action(
        db=db,
        action="INVENTORY_EXPIRY_SWEEP",
        entity="blood_inventory",
        user_id=current_user.user_id,
    )
    db.commit()

    return ExpiryScanResponse(
        scanned_count=scanned_count,
        expiring_soon_count=expiring_count,
        expiring_items=expiring_items,
        message=f"Expiry scan completed: {expiring_count} of {scanned_count} units expiring within 72 hours.",
    )
