"""Blood Compatibility Matrix mapping recipient blood group to compatible donor blood groups."""
from typing import List, Dict
from app.core.enums import BloodGroup

COMPATIBILITY_MATRIX: Dict[BloodGroup, List[BloodGroup]] = {
    BloodGroup.O_MINUS: [
        BloodGroup.O_MINUS,
    ],
    BloodGroup.O_PLUS: [
        BloodGroup.O_MINUS,
        BloodGroup.O_PLUS,
    ],
    BloodGroup.A_MINUS: [
        BloodGroup.O_MINUS,
        BloodGroup.A_MINUS,
    ],
    BloodGroup.A_PLUS: [
        BloodGroup.O_MINUS,
        BloodGroup.O_PLUS,
        BloodGroup.A_MINUS,
        BloodGroup.A_PLUS,
    ],
    BloodGroup.B_MINUS: [
        BloodGroup.O_MINUS,
        BloodGroup.B_MINUS,
    ],
    BloodGroup.B_PLUS: [
        BloodGroup.O_MINUS,
        BloodGroup.O_PLUS,
        BloodGroup.B_MINUS,
        BloodGroup.B_PLUS,
    ],
    BloodGroup.AB_MINUS: [
        BloodGroup.O_MINUS,
        BloodGroup.A_MINUS,
        BloodGroup.B_MINUS,
        BloodGroup.AB_MINUS,
    ],
    BloodGroup.AB_PLUS: [
        BloodGroup.O_MINUS,
        BloodGroup.O_PLUS,
        BloodGroup.A_MINUS,
        BloodGroup.A_PLUS,
        BloodGroup.B_MINUS,
        BloodGroup.B_PLUS,
        BloodGroup.AB_MINUS,
        BloodGroup.AB_PLUS,
    ],
}


def get_compatible_donor_groups(recipient_group: BloodGroup) -> List[BloodGroup]:
    """Return compatible donor blood groups for a given recipient blood group."""
    return COMPATIBILITY_MATRIX.get(recipient_group, [])


def is_blood_compatible(recipient_group: BloodGroup, donor_group: BloodGroup) -> bool:
    """Check if a specific donor blood group is compatible with a recipient blood group."""
    return donor_group in COMPATIBILITY_MATRIX.get(recipient_group, [])
