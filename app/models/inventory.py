"""Blood inventory and stock transaction models."""
import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column,
    String,
    Date,
    DateTime,
    Numeric,
    ForeignKey,
    Enum as SQLEnum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.enums import (
    BloodGroup,
    ComponentType,
    StockStatus,
    TransactionType,
)


class BloodInventory(Base):
    __tablename__ = "blood_inventory"

    inventory_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hospital_id = Column(
        UUID(as_uuid=True),
        ForeignKey("hospitals.hospital_id", ondelete="CASCADE"),
        nullable=False,
    )
    blood_group = Column(SQLEnum(BloodGroup, name="blood_group_enum"), nullable=False)
    component_type = Column(SQLEnum(ComponentType, name="component_type_enum"), nullable=False)
    quantity = Column(Numeric(5, 2), nullable=False)
    unit = Column(String(10), default="ml/unit", nullable=False)
    expiry_date = Column(Date, nullable=False)
    status = Column(
        SQLEnum(StockStatus, name="stock_status_enum"),
        default=StockStatus.HEALTHY,
        nullable=False,
    )
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    # Relationships
    hospital = relationship("Hospital", back_populates="inventory")
    transactions = relationship("InventoryTransaction", back_populates="inventory", cascade="all, delete-orphan")


class InventoryTransaction(Base):
    __tablename__ = "inventory_transaction"

    transaction_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inventory_id = Column(
        UUID(as_uuid=True),
        ForeignKey("blood_inventory.inventory_id", ondelete="CASCADE"),
        nullable=False,
    )
    type = Column(SQLEnum(TransactionType, name="transaction_type_enum"), nullable=False)
    quantity = Column(Numeric(5, 2), nullable=False)
    reference_type = Column(String(20), nullable=True)  # e.g., 'DONATION', 'REQUEST', 'EVENT', 'ADJUSTMENT'
    reference_id = Column(UUID(as_uuid=True), nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())

    # Relationships
    inventory = relationship("BloodInventory", back_populates="transactions")
    creator = relationship("User")
