import json
import logging
from pathlib import Path
from schemas.blueprint_schema import Blueprint
from utils.exceptions import BlueprintLoadError

logger = logging.getLogger(__name__)

class BlueprintService:
    BLUEPRINT_DIR = Path("blueprints")

    @classmethod
    def _resolve_blueprint_path(cls, blueprint_filename: str) -> Path:
        """Resolves a blueprint filename to an actual file on disk.
        
        Handles cases where the frontend sends partial names like 'gst_itc'
        instead of the full filename 'gst_blueprint.json'.
        """
        # 1. Try exact match first
        file_path = cls.BLUEPRINT_DIR / blueprint_filename
        if file_path.exists():
            return file_path
        
        # 2. Try appending .json if missing
        if not blueprint_filename.endswith(".json"):
            json_path = cls.BLUEPRINT_DIR / f"{blueprint_filename}.json"
            if json_path.exists():
                return json_path
        
        # 3. Try glob for files containing the given name
        matches = list(cls.BLUEPRINT_DIR.glob(f"*{blueprint_filename}*"))
        json_matches = [m for m in matches if m.suffix == ".json"]
        if json_matches:
            logger.info(f"Resolved blueprint '{blueprint_filename}' -> '{json_matches[0].name}'")
            return json_matches[0]
        
        return None

    @classmethod
    def load_blueprint(cls, blueprint_filename: str) -> Blueprint:
        """Loads and strictly validates a JSON blueprint."""
        file_path = cls._resolve_blueprint_path(blueprint_filename)
        
        if file_path is None:
            logger.error(f"Blueprint not found: {blueprint_filename}")
            # Fall back to first available blueprint if any exist
            available = cls.get_available_blueprints()
            if available:
                logger.info(f"Falling back to default blueprint: {available[0]}")
                file_path = cls.BLUEPRINT_DIR / available[0]
            else:
                raise BlueprintLoadError(f"Blueprint '{blueprint_filename}' does not exist and no fallback available.")
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Blueprint(**data)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in blueprint {blueprint_filename}: {e}")
            raise BlueprintLoadError(f"Failed to parse JSON: {e}")
        except Exception as e:
            logger.error(f"Validation failed for blueprint {blueprint_filename}: {e}")
            raise BlueprintLoadError(f"Invalid Blueprint schema: {e}")
    
    @classmethod
    def get_available_blueprints(cls) -> list[str]:
        """Scans the blueprints directory and returns a list of available JSON filenames."""
        if not cls.BLUEPRINT_DIR.exists():
            cls.BLUEPRINT_DIR.mkdir(parents=True, exist_ok=True)
            return []

        # Returns a list like ['gst_comprehensive_2026.json', 'rbi_digital_lending.json']
        return [f.name for f in cls.BLUEPRINT_DIR.glob("*.json")]

    @classmethod
    async def seed_system_blueprints(cls, db):
        """Load all blueprints/*.json and blueprints/notices/*.json into DB as system records.

        Idempotent — skips any blueprint whose name already exists as a system record.
        Audit blueprints get category="audit", notice blueprints get category="notice".
        """
        from sqlalchemy import select
        from db.models.core import Blueprint as BlueprintModel

        if not cls.BLUEPRINT_DIR.exists():
            logger.warning("Blueprints directory not found, skipping seed.")
            return

        # Collect audit blueprints (top-level) and notice blueprints (notices/ subdir)
        blueprint_files = []
        for f in cls.BLUEPRINT_DIR.iterdir():
            if f.suffix == ".json" and f.is_file():
                blueprint_files.append((f, "audit"))

        notices_dir = cls.BLUEPRINT_DIR / "notices"
        if notices_dir.exists():
            for f in notices_dir.iterdir():
                if f.suffix == ".json" and f.is_file():
                    blueprint_files.append((f, "notice"))

        seeded = 0
        updated = 0

        for json_file, category in blueprint_files:
            try:
                with open(json_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                bp = Blueprint(**data)

                # Check if system blueprint with this name already exists
                result = await db.execute(
                    select(BlueprintModel).where(
                        BlueprintModel.user_id.is_(None),
                        BlueprintModel.name == bp.name,
                    )
                )
                existing = result.scalar_one_or_none()
                if existing:
                    # Ensure category is correct on existing blueprints
                    if getattr(existing, 'category', 'audit') != category:
                        existing.category = category
                        updated += 1
                    continue

                new_bp = BlueprintModel(
                    user_id=None,
                    name=bp.name,
                    description=bp.description,
                    rules_json=[check.model_dump() for check in bp.checks],
                    category=category,
                )
                db.add(new_bp)
                seeded += 1
            except Exception as e:
                logger.error(f"Failed to seed blueprint {json_file.name}: {e}")

        if seeded > 0 or updated > 0:
            await db.commit()
        logger.info(f"System blueprints: {seeded} new, {updated} updated, {len(blueprint_files)} total on disk.")