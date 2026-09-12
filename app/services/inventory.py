"""Inventory Health and Expiry Scanning Engine.

Rules:
- Status Calculation (Mapping stock-to-minimum-threshold ratios):
  - Minimum nominal capacity/threshold: 50.0 units
  - Ratio > 50% -> HEALTHY
  - 20% <= Ratio <= 50% -> LOW_STOCK
  - Ratio < 20% -> CRITICAL
  - Ratio == 0 -> OUT_OF_STOCK
- Scan Expiries:
  - Query items where expiry_date <= CURRENT_DATE + 72 hours
"""
from datetime import date, timedelta
from typing import Tuple, List, Dict, Any
from sqlalchemy.orm import Session, joinedload
from app.models.inventory import BloodInventory
from app.core.enums import StockStatus

NOMINAL_MINIMUM_THRESHOLD = 50.0  # nominal threshold in ml/units


def calculate_stock_status(quantity: float, threshold: float = NOMINAL_MINIMUM_THRESHOLD) -> StockStatus:
    """Calculate StockStatus based on stock-to-threshold ratio."""
    if quantity <= 0:
        return StockStatus.OUT_OF_STOCK

    ratio = (quantity / threshold) * 100.0

    if ratio > 50.0:
        return StockStatus.HEALTHY
    elif 20.0 <= ratio <= 50.0:
        return StockStatus.LOW_STOCK
    else:
        return StockStatus.CRITICAL


def scan_inventory_expiries(db: Session, hours: int = 72) -> Tuple[int, int, List[Dict[str, Any]]]:
    """Sweep inventory for units expiring within specified hours (default 72 hours)."""
    today = date.today()
    cutoff_date = today + timedelta(days=(hours // 24))

    all_items = (
        db.query(BloodInventory)
        .options(joinedload(BloodInventory.hospital))
        .all()
    )
    scanned_count = len(all_items)

    expiring_items: List[Dict[str, Any]] = []
    for item in all_items:
        if item.expiry_date <= cutoff_date:
            days_left = (item.expiry_date - today).days
            hours_left = max(0.0, float(days_left * 24))

            # Mark critical if near expiry
            if item.status != StockStatus.OUT_OF_STOCK:
                item.status = StockStatus.CRITICAL

            expiring_items.append({
                "inventory_id": item.inventory_id,
                "hospital_name": item.hospital.hospital_name if item.hospital else "Unknown Center",
                "blood_group": item.blood_group,
                "component_type": item.component_type,
                "quantity": float(item.quantity),
                "expiry_date": item.expiry_date,
                "hours_remaining": hours_left,
            })

    db.commit()
    return scanned_count, len(expiring_items), expiring_items
