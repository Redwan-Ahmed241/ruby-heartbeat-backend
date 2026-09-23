"""Automated Donor Eligibility Validator.

Rules:
- Age: Must be between 18 and 65 years old.
- Weight: Must be >= 50 kg.
- Hemoglobin Level: Must be >= 12.5 g/dL (from medical_info.hemoglobin_level).
- Recovery Period: Cooldown since last_donation_date:
  - WHOLE_BLOOD: at least 90 days.
  - PLATELETS / PLASMA: at least 14 days.
"""
from datetime import date, timedelta
from typing import List, Tuple, Optional
from app.models.user import Donor
from app.core.enums import ComponentType


def calculate_age(born: date, today: Optional[date] = None) -> int:
    if today is None:
        today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def calculate_donor_tier(donation_count: int) -> Tuple[str, str, int]:
    """Calculate donor achievement tier and ranking priority based on completed donations.
    
    Standardized Tiers (Doc Section 8):
    - Diamond: >= 10 verified donations (Highest honor, badge: 💎, priority: 4)
    - Platinum: 6-9 verified donations (badge: ⚡, priority: 3)
    - Silver: 3-5 verified donations (badge: 🥈, priority: 2)
    - Bronze: 1-2 verified donations (badge: 🥉, priority: 1)
    - New: 0 verified donations (badge: 🩸, priority: 0)
    
    Returns:
        Tuple of (tier_name, badge_icon, priority_weight)
    """
    if donation_count >= 10:
        return "Diamond", "💎", 4
    elif donation_count >= 6:
        return "Platinum", "⚡", 3
    elif donation_count >= 3:
        return "Silver", "🥈", 2
    elif donation_count >= 1:
        return "Bronze", "🥉", 1
    else:
        return "New", "🩸", 0



def check_donor_eligibility(
    donor: Donor,
    target_component: ComponentType = ComponentType.WHOLE_BLOOD,
    today: Optional[date] = None,
) -> Tuple[bool, List[str], dict]:
    """Validate a donor's eligibility and return (is_eligible, rejection_reasons, metrics)."""
    if today is None:
        today = date.today()

    rejections: List[str] = []
    
    # 1. Age check (18 - 65)
    age = donor.age if getattr(donor, "age", None) is not None else calculate_age(donor.date_of_birth, today)
    if age < 18:
        rejections.append("Underage: Must be at least 18 years old to donate blood.")
    elif age > 65:
        rejections.append("Maximum eligible age for regular blood donation is 65 years.")

    # 2. Weight check (>= 50 kg)
    weight = float(donor.weight) if donor.weight is not None else 0.0
    if weight < 50.0:
        rejections.append(f"Weight is below the minimum required 50.0 kg (current weight: {weight:.1f} kg).")

    # 3. Hemoglobin check (>= 12.5 g/dL)
    hb_level = None
    if donor.medical_info and donor.medical_info.hemoglobin_level is not None:
        hb_level = float(donor.medical_info.hemoglobin_level)
        if hb_level < 12.5:
            rejections.append(f"Hemoglobin level is below 12.5 g/dL (current level: {hb_level:.1f} g/dL).")
    else:
        rejections.append("Donor has no medical profile or hemoglobin level recorded.")

    # 4. Recovery / Cooldown period check
    days_since_donation = None
    cooldown_active = False
    next_eligible_date = None
    cooldown_days_remaining = None

    if donor.last_donation_date:
        days_since_donation = (today - donor.last_donation_date).days
        min_days = 90 if target_component == ComponentType.WHOLE_BLOOD else 14
        next_eligible_date = donor.last_donation_date + timedelta(days=min_days)
        if days_since_donation < min_days:
            cooldown_active = True
            cooldown_days_remaining = min_days - days_since_donation
            rejections.append(
                f"Donor is in recovery cooldown ({days_since_donation} days since last donation; "
                f"minimum required for {target_component.value} is {min_days} days). "
                f"Next eligible donation date: {next_eligible_date.strftime('%Y-%m-%d')}."
            )
        else:
            cooldown_days_remaining = 0

    is_eligible = len(rejections) == 0

    metrics = {
        "age": age,
        "weight": weight,
        "hemoglobin_level": hb_level,
        "days_since_last_donation": days_since_donation,
        "last_donation_date": donor.last_donation_date,
        "cooldown_active": cooldown_active,
        "next_eligible_date": next_eligible_date,
        "cooldown_days_remaining": cooldown_days_remaining,
    }

    return is_eligible, rejections, metrics
