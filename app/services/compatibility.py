"""Blood Compatibility Matrix mapping recipient blood group to compatible donor blood groups."""
from typing import List, Dict
from app.core.enums import BloodGroup

COMPATIBILITY_MATRIX: Dict[BloodGroup, List[BloodGroup]] = {
    BloodGroup.O_NEGATIVE: [
        BloodGroup.O_NEGATIVE,
    ],
    BloodGroup.O_POSITIVE: [
        BloodGroup.O_NEGATIVE,
        BloodGroup.O_POSITIVE,
    ],
    BloodGroup.A_NEGATIVE: [
        BloodGroup.O_NEGATIVE,
        BloodGroup.A_NEGATIVE,
    ],
    BloodGroup.A_POSITIVE: [
        BloodGroup.O_NEGATIVE,
        BloodGroup.O_POSITIVE,
        BloodGroup.A_NEGATIVE,
        BloodGroup.A_POSITIVE,
    ],
    BloodGroup.B_NEGATIVE: [
        BloodGroup.O_NEGATIVE,
        BloodGroup.B_NEGATIVE,
    ],
    BloodGroup.B_POSITIVE: [
        BloodGroup.O_NEGATIVE,
        BloodGroup.O_POSITIVE,
        BloodGroup.B_NEGATIVE,
        BloodGroup.B_POSITIVE,
    ],
    BloodGroup.AB_NEGATIVE: [
        BloodGroup.O_NEGATIVE,
        BloodGroup.A_NEGATIVE,
        BloodGroup.B_NEGATIVE,
        BloodGroup.AB_NEGATIVE,
    ],
    BloodGroup.AB_POSITIVE: [
        BloodGroup.O_NEGATIVE,
        BloodGroup.O_POSITIVE,
        BloodGroup.A_NEGATIVE,
        BloodGroup.A_POSITIVE,
        BloodGroup.B_NEGATIVE,
        BloodGroup.B_POSITIVE,
        BloodGroup.AB_NEGATIVE,
        BloodGroup.AB_POSITIVE,
    ],
}


def get_compatible_donor_groups(recipient_group: BloodGroup) -> List[BloodGroup]:
    """Return compatible donor blood groups for a given recipient blood group."""
    return COMPATIBILITY_MATRIX.get(recipient_group, [])


def is_blood_compatible(recipient_group: BloodGroup, donor_group: BloodGroup) -> bool:
    """Check if a specific donor blood group is compatible with a recipient blood group."""
    return donor_group in COMPATIBILITY_MATRIX.get(recipient_group, [])
