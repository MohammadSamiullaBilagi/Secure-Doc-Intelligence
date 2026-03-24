import logging
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from db.models.calendar import TaxDeadline, UserReminder

logger = logging.getLogger(__name__)


class CalendarService:
    """Business logic for tax calendar deadlines and reminders."""

    @staticmethod
    def _compute_current_fy(today: date) -> tuple[int, int]:
        """Return (start_year, end_year) for the Indian FY containing `today`.

        Indian FY runs Apr 1 – Mar 31.  E.g. 2026-03-19 → (2025, 2026),
        2026-04-01 → (2026, 2027).
        """
        if today.month >= 4:
            return today.year, today.year + 1
        return today.year - 1, today.year

    @staticmethod
    def _seed_fy_deadlines(fy_start_year: int) -> list[TaxDeadline]:
        """Build TaxDeadline objects for one Indian FY (Apr of fy_start_year to Mar of fy_start_year+1)."""
        fy_end_year = fy_start_year + 1
        deadlines: list[TaxDeadline] = []

        # GSTR-1: 11th of every month (for previous month)
        for month in range(4, 13):  # Apr – Dec
            deadlines.append(TaxDeadline(
                title=f"GSTR-1 Filing - {date(fy_start_year, month, 1).strftime('%B %Y')}",
                due_date=date(fy_start_year, month, 11),
                category="GST",
                description="Monthly return for outward supplies",
                is_system=True,
            ))
        for month in range(1, 4):  # Jan – Mar
            deadlines.append(TaxDeadline(
                title=f"GSTR-1 Filing - {date(fy_end_year, month, 1).strftime('%B %Y')}",
                due_date=date(fy_end_year, month, 11),
                category="GST",
                description="Monthly return for outward supplies",
                is_system=True,
            ))

        # GSTR-3B: 20th of every month
        for month in range(4, 13):
            deadlines.append(TaxDeadline(
                title=f"GSTR-3B Filing - {date(fy_start_year, month, 1).strftime('%B %Y')}",
                due_date=date(fy_start_year, month, 20),
                category="GST",
                description="Monthly summary return with tax payment",
                is_system=True,
            ))
        for month in range(1, 4):
            deadlines.append(TaxDeadline(
                title=f"GSTR-3B Filing - {date(fy_end_year, month, 1).strftime('%B %Y')}",
                due_date=date(fy_end_year, month, 20),
                category="GST",
                description="Monthly summary return with tax payment",
                is_system=True,
            ))

        # TDS: 7th of every month
        for month in range(4, 13):
            deadlines.append(TaxDeadline(
                title=f"TDS Payment - {date(fy_start_year, month, 1).strftime('%B %Y')}",
                due_date=date(fy_start_year, month, 7),
                category="TDS",
                description="Monthly TDS deposit to government",
                is_system=True,
            ))
        for month in range(1, 4):
            deadlines.append(TaxDeadline(
                title=f"TDS Payment - {date(fy_end_year, month, 1).strftime('%B %Y')}",
                due_date=date(fy_end_year, month, 7),
                category="TDS",
                description="Monthly TDS deposit to government",
                is_system=True,
            ))

        # Advance Tax quarterly deadlines
        advance_tax = [
            (date(fy_start_year, 6, 15), "Q1 Advance Tax (15% of estimated tax)"),
            (date(fy_start_year, 9, 15), "Q2 Advance Tax (45% cumulative)"),
            (date(fy_start_year, 12, 15), "Q3 Advance Tax (75% cumulative)"),
            (date(fy_end_year, 3, 15), "Q4 Advance Tax (100% cumulative)"),
        ]
        for due, desc in advance_tax:
            deadlines.append(TaxDeadline(
                title=f"Advance Tax - {due.strftime('%B %Y')}",
                due_date=due,
                category="Advance Tax",
                description=desc,
                is_system=True,
            ))

        # ITR filing deadline
        deadlines.append(TaxDeadline(
            title="Income Tax Return Filing (Non-Audit)",
            due_date=date(fy_start_year, 7, 31),
            category="Income Tax",
            description="Due date for individuals and non-audit entities",
            is_system=True,
        ))

        # Tax Audit Report deadline
        deadlines.append(TaxDeadline(
            title="Tax Audit Report (Section 44AB)",
            due_date=date(fy_start_year, 9, 30),
            category="Income Tax",
            description="Due date for tax audit report filing",
            is_system=True,
        ))

        # ITR for audited entities
        deadlines.append(TaxDeadline(
            title="ITR Filing (Audit Cases)",
            due_date=date(fy_start_year, 10, 31),
            category="Income Tax",
            description="Due date for entities requiring tax audit",
            is_system=True,
        ))

        return deadlines

    @staticmethod
    async def _fy_already_seeded(db: AsyncSession, fy_start_year: int) -> bool:
        """Check if system deadlines already exist in the date range of this FY."""
        fy_start = date(fy_start_year, 4, 1)
        fy_end = date(fy_start_year + 1, 3, 31)
        result = await db.execute(
            select(func.count(TaxDeadline.id)).where(
                TaxDeadline.is_system == True,
                TaxDeadline.due_date >= fy_start,
                TaxDeadline.due_date <= fy_end,
            )
        )
        count = result.scalar()
        return bool(count and count > 0)

    @staticmethod
    async def seed_indian_deadlines(db: AsyncSession):
        """Idempotent seeding of Indian tax deadlines for current FY + next FY."""
        today = date.today()
        current_start, _ = CalendarService._compute_current_fy(today)
        next_start = current_start + 1

        seeded_any = False
        for fy_start in (current_start, next_start):
            if await CalendarService._fy_already_seeded(db, fy_start):
                logger.info(f"Tax deadlines for FY {fy_start}-{(fy_start + 1) % 100:02d} already seeded. Skipping.")
                continue

            deadlines = CalendarService._seed_fy_deadlines(fy_start)
            db.add_all(deadlines)
            seeded_any = True
            logger.info(f"Seeded {len(deadlines)} Indian tax deadlines for FY {fy_start}-{(fy_start + 1) % 100:02d}.")

        if seeded_any:
            await db.commit()

    @staticmethod
    async def get_upcoming_deadlines(days_ahead: int, db: AsyncSession) -> list:
        """Get deadlines within the next N days."""
        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        result = await db.execute(
            select(TaxDeadline)
            .where(TaxDeadline.due_date >= today, TaxDeadline.due_date <= end_date)
            .order_by(TaxDeadline.due_date)
        )
        return result.scalars().all()

    @staticmethod
    async def get_user_reminders(user_id: UUID, db: AsyncSession) -> list:
        """Get all active reminders for a user, eagerly loading the deadline."""
        result = await db.execute(
            select(UserReminder)
            .options(selectinload(UserReminder.deadline))
            .where(UserReminder.user_id == user_id, UserReminder.is_active == True)
        )
        return result.scalars().all()
