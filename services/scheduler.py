import logging
from datetime import date, datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from services.cleanup_service import CleanupService
from services.scraper_service import KnowledgeFreshnessService

logger = logging.getLogger(__name__)


def dispatch_due_reminders():
    """Check for reminders due today and send email notifications.

    Uses sync SQLAlchemy session (runs in APScheduler background thread).
    """
    from services.email_service import EmailService

    if not EmailService.is_configured():
        return

    try:
        from sqlalchemy import select
        from Database.database import SessionLocal
        from db.models.calendar import UserReminder, TaxDeadline
        from db.models.core import User, UserPreference

        db = SessionLocal()
        today = date.today()

        try:
            # Fetch all active, unsent email reminders with joined data
            stmt = (
                select(
                    UserReminder,
                    TaxDeadline.title,
                    TaxDeadline.due_date,
                    User.email,
                    UserPreference.preferred_email,
                    UserPreference.ca_name,
                )
                .join(TaxDeadline, UserReminder.deadline_id == TaxDeadline.id)
                .join(User, UserReminder.user_id == User.id)
                .outerjoin(UserPreference, UserPreference.user_id == UserReminder.user_id)
                .where(
                    UserReminder.is_active == True,
                    UserReminder.sent_at == None,
                    UserReminder.channel == "email",
                )
            )

            rows = db.execute(stmt).all()

            for reminder, deadline_name, due_date_val, user_email, preferred_email, ca_name in rows:
                days_remaining = (due_date_val - today).days

                if days_remaining != reminder.remind_days_before:
                    continue

                to_email = preferred_email or user_email
                if not to_email:
                    continue

                success = EmailService.send_deadline_reminder(
                    to=to_email,
                    ca_name=ca_name or "",
                    deadline_name=deadline_name,
                    due_date_str=due_date_val.strftime("%d/%m/%Y"),
                    days_remaining=days_remaining,
                    reply_to=user_email,  # CA's login email for replies
                )

                if success:
                    reminder.sent_at = datetime.now(timezone.utc)

            db.commit()
            logger.info("Reminder dispatch completed.")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Reminder dispatch failed: {e}")


def start_background_tasks():
    """Initializes the production job scheduler."""
    scheduler = BackgroundScheduler()

    # 1. Heartbeat TTL Sweep (Runs every hour)
    scheduler.add_job(CleanupService.sweep_stale_sessions, 'interval', hours=1, id='ttl_sweep')

    # 2. Knowledge Freshness Scrape (Runs every Sunday at 2 AM)
    scraper = KnowledgeFreshnessService()
    scheduler.add_job(scraper.run_weekly_update, 'cron', day_of_week='sun', hour=2, id='global_scrape')

    # 3. Email Reminder Dispatch (Daily at 8:00 AM IST = 2:30 AM UTC)
    scheduler.add_job(dispatch_due_reminders, 'cron', hour=2, minute=30, id='reminder_dispatch')

    scheduler.start()
    logger.info("Background Job Scheduler initialized and running.")
