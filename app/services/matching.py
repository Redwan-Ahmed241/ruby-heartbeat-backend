"""Intelligent Real-Time Matching Engine.

Implements:
1. Hard Filters:
   - Compatibility list for requested blood group.
   - Availability status == AVAILABLE.
   - Passes automated Donor Eligibility Service.
2. Spatial Haversine Distance & Progressive Radius Expansion:
   - Initial 10 km -> If < 3 candidates, expand to 25 km -> 50 km.
   - For EMERGENCY: bypass queue and search up to 50 km immediately.
3. Composite Scoring Formula:
   - DistanceScore = 1 / (1 + distance_km)
   - ReliabilityScore = completed_donations / max(total_matches, 1)
   - RecencyPenalty = scalar (0.0 to 1.0 based on distance past cooldown threshold)
   - BaseScore = (0.5 * DistanceScore) + (0.3 * ReliabilityScore) + (0.2 * RecencyPenalty)
   - Urgency Multiplier:
     - EMERGENCY: 1.5x
     - URGENT: 1.2x
     - NORMAL: 1.0x
   - FinalScore = BaseScore * UrgencyMultiplier
4. Ranking & Persistence:
   - Saves matches to donor_match table.
   - Logs/dispatches notification and sets is_notified = True.
"""
import math
import logging
from datetime import date
from typing import List, Tuple
from sqlalchemy.orm import Session, joinedload
from app.models.user import Donor, DonationHistory
from app.models.request import BloodRequest, DonorMatch
from app.core.enums import (
    AvailabilityStatus,
    RequestUrgency,
    MatchResponseStatus,
    ComponentType,
)
from app.services.compatibility import get_compatible_donor_groups
from app.services.eligibility import check_donor_eligibility

logger = logging.getLogger(__name__)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Great-Circle distance between two coordinates in kilometers."""
    r = 6371.0  # Earth's radius in km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def calculate_recency_score(donor: Donor, component: ComponentType, today: date) -> float:
    """Calculate recency score/penalty (0.0 to 1.0).
    A donor who has had ample rest past the minimum cooldown gets a higher readiness score.
    """
    if not donor.last_donation_date:
        return 1.0  # First-time donor or fully rested

    days_since = (today - donor.last_donation_date).days
    min_cooldown = 90 if component == ComponentType.WHOLE_BLOOD else 14

    if days_since < min_cooldown:
        return 0.0

    # Scale smoothly from min_cooldown to min_cooldown * 2
    excess = days_since - min_cooldown
    score = min(1.0, 0.5 + (excess / (min_cooldown * 2)))
    return score


def calculate_reliability_score(db: Session, donor: Donor) -> float:
    """Calculate donor reliability: completed / max(total_matches, 1)."""
    total_matches = (
        db.query(DonorMatch).filter(DonorMatch.donor_id == donor.donor_id).count()
    )
    if total_matches == 0:
        return 0.8  # Default encouraging score for fresh donors

    accepted_matches = (
        db.query(DonorMatch)
        .filter(
            DonorMatch.donor_id == donor.donor_id,
            DonorMatch.response_status == MatchResponseStatus.ACCEPTED,
        )
        .count()
    )
    return accepted_matches / float(total_matches)


def run_matching_engine(
    db: Session,
    request: BloodRequest,
    is_emergency: bool = False,
) -> List[DonorMatch]:
    """Execute the full matching pipeline and persist matches."""
    today = date.today()
    req_lat = float(request.latitude)
    req_lon = float(request.longitude)

    # 1. Compatibility list
    compatible_groups = get_compatible_donor_groups(request.blood_group)

    # 2. Query available donors with compatible blood groups
    donors_query = (
        db.query(Donor)
        .options(joinedload(Donor.medical_info), joinedload(Donor.user))
        .filter(
            Donor.blood_group.in_(compatible_groups),
            Donor.availability_status == AvailabilityStatus.AVAILABLE,
        )
        .all()
    )

    # 3. Filter eligible donors
    eligible_candidates: List[Donor] = []
    for donor in donors_query:
        eligible, _, _ = check_donor_eligibility(
            donor, target_component=request.component_type, today=today
        )
        if eligible:
            eligible_candidates.append(donor)

    # 4. Spatial Radius Expansion
    # Emergency bypasses progressive expansion and searches 50 km immediately
    radii = [50.0] if is_emergency else [10.0, 25.0, 50.0]
    
    candidate_distances: List[Tuple[Donor, float]] = []
    
    for radius in radii:
        current_in_radius: List[Tuple[Donor, float]] = []
        for donor in eligible_candidates:
            d_lat = float(donor.latitude)
            d_lon = float(donor.longitude)
            dist = haversine_distance(req_lat, req_lon, d_lat, d_lon)
            if dist <= radius:
                current_in_radius.append((donor, dist))
        
        candidate_distances = current_in_radius
        if len(candidate_distances) >= 3 or radius >= 50.0 or is_emergency:
            break

    # 5. Composite Scoring Formula
    # Urgency Multiplier
    urgency_multiplier = 1.0
    if request.urgency == RequestUrgency.EMERGENCY or is_emergency:
        urgency_multiplier = 1.5
    elif request.urgency == RequestUrgency.URGENT:
        urgency_multiplier = 1.2

    scored_candidates = []
    for donor, dist_km in candidate_distances:
        distance_score = 1.0 / (1.0 + dist_km)
        reliability_score = calculate_reliability_score(db, donor)
        recency_score = calculate_recency_score(donor, request.component_type, today)

        base_score = (
            (0.5 * distance_score)
            + (0.3 * reliability_score)
            + (0.2 * recency_score)
        )
        final_score = base_score * urgency_multiplier

        # Normalize score between 0 and 100 for user readability and persistence
        normalized_score = round(final_score * 50.0, 2)

        scored_candidates.append((donor, dist_km, normalized_score))

    # Sort descending by FinalScore
    scored_candidates.sort(key=lambda x: x[2], reverse=True)

    # 6. Ranking & Dispatch: Persist in donor_match
    matches: List[DonorMatch] = []
    for donor, dist_km, score in scored_candidates:
        match_record = DonorMatch(
            request_id=request.request_id,
            donor_id=donor.donor_id,
            match_score=score,
            distance_km=round(dist_km, 2),
            is_notified=True,  # Dispatched notification flag
            response_status=MatchResponseStatus.PENDING,
        )
        db.add(match_record)
        matches.append(match_record)
        logger.info(
            f"[NOTIFICATION DISPATCH] Notified donor {donor.donor_id} for request {request.request_id} "
            f"(Score: {score}, Distance: {dist_km:.2f}km)"
        )

    db.flush()
    return matches
