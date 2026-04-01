import enum
import uuid
from datetime import date, datetime

from dateutils import utcnow
from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class PropertyType(str, enum.Enum):
    efh = "efh"
    mfh = "mfh"
    stockwerk = "stockwerk"
    grundstueck = "grundstueck"


class MortgageType(str, enum.Enum):
    fixed = "fixed"
    saron = "saron"
    variable = "variable"


class ExpenseCategory(str, enum.Enum):
    insurance = "insurance"
    utilities = "utilities"
    maintenance = "maintenance"
    repair = "repair"
    tax = "tax"
    other = "other"


class Frequency(str, enum.Enum):
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"
    once = "once"


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    property_type: Mapped[PropertyType] = mapped_column(Enum(PropertyType), nullable=False)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    estimated_value: Mapped[float | None] = mapped_column(Numeric(12, 2))
    estimated_value_date: Mapped[date | None] = mapped_column(Date)
    land_area_m2: Mapped[float | None] = mapped_column(Numeric(10, 2))
    living_area_m2: Mapped[float | None] = mapped_column(Numeric(10, 2))
    rooms: Mapped[float | None] = mapped_column(Numeric(3, 1))
    year_built: Mapped[int | None] = mapped_column(Integer)
    canton: Mapped[str | None] = mapped_column(String(2))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    mortgages: Mapped[list["Mortgage"]] = relationship(back_populates="property", cascade="all, delete-orphan")
    expenses: Mapped[list["PropertyExpense"]] = relationship(back_populates="property", cascade="all, delete-orphan")
    incomes: Mapped[list["PropertyIncome"]] = relationship(back_populates="property", cascade="all, delete-orphan")


class Mortgage(Base):
    __tablename__ = "mortgages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[MortgageType] = mapped_column(Enum(MortgageType), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    interest_rate: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False)
    margin_rate: Mapped[float | None] = mapped_column(Numeric(5, 3))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    monthly_payment: Mapped[float | None] = mapped_column(Numeric(12, 2))
    annual_payment: Mapped[float | None] = mapped_column(Numeric(12, 2))
    amortization_monthly: Mapped[float | None] = mapped_column(Numeric(12, 2))
    amortization_annual: Mapped[float | None] = mapped_column(Numeric(12, 2))
    bank: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted PII
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    property: Mapped["Property"] = relationship(back_populates="mortgages")


class PropertyExpense(Base):
    __tablename__ = "property_expenses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[ExpenseCategory] = mapped_column(Enum(ExpenseCategory), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    frequency: Mapped[Frequency | None] = mapped_column(Enum(Frequency))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    property: Mapped["Property"] = relationship(back_populates="expenses")


class PropertyIncome(Base):
    __tablename__ = "property_income"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    tenant: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted PII
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    frequency: Mapped[Frequency | None] = mapped_column(Enum(Frequency))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    property: Mapped["Property"] = relationship(back_populates="incomes")
