"""Application core enums."""
from enum import Enum


class UserRole(str, Enum):
    DONOR = "DONOR"
    RECIPIENT = "RECIPIENT"
    HOSPITAL_ADMIN = "HOSPITAL_ADMIN"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"


class BloodGroup(str, Enum):
    A_PLUS = "A_PLUS"
    A_MINUS = "A_MINUS"
    B_PLUS = "B_PLUS"
    B_MINUS = "B_MINUS"
    AB_PLUS = "AB_PLUS"
    AB_MINUS = "AB_MINUS"
    O_PLUS = "O_PLUS"
    O_MINUS = "O_MINUS"


class ComponentType(str, Enum):
    WHOLE_BLOOD = "WHOLE_BLOOD"
    PLASMA = "PLASMA"
    PLATELETS = "PLATELETS"


class RequestUrgency(str, Enum):
    NORMAL = "NORMAL"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


class RequestStatus(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StockStatus(str, Enum):
    HEALTHY = "HEALTHY"
    LOW_STOCK = "LOW_STOCK"
    CRITICAL = "CRITICAL"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class MatchResponseStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventStatus(str, Enum):
    UPCOMING = "UPCOMING"
    ONGOING = "ONGOING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ParticipantRole(str, Enum):
    ORGANIZER = "ORGANIZER"
    PARTICIPANT = "PARTICIPANT"
    VOLUNTEER = "VOLUNTEER"


class ParticipantStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ATTENDED = "ATTENDED"
    CANCELLED = "CANCELLED"


class TransactionType(str, Enum):
    IN = "IN"
    OUT = "OUT"
    ADJUSTMENT = "ADJUSTMENT"


class CommunicationChannel(str, Enum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"
