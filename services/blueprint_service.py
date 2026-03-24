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
        """Load all blueprints/*.json files into DB as system records (user_id=NULL).

        Idempotent — skips any blueprint whose name already exists as a system record.
        """
        from sqlalchemy import select
        from db.models.core import Blueprint as BlueprintModel

        if not cls.BLUEPRINT_DIR.exists():
            logger.warning("Blueprints directory not found, skipping seed.")
            return

        json_files = [f for f in cls.BLUEPRINT_DIR.iterdir() if f.suffix == ".json" and f.is_file()]
        seeded = 0

        for json_file in json_files:
            try:
                bp = cls.load_blueprint(json_file.name)

                # Check if system blueprint with this name already exists
                result = await db.execute(
                    select(BlueprintModel).where(
                        BlueprintModel.user_id.is_(None),
                        BlueprintModel.name == bp.name,
                    )
                )
                existing = result.scalar_one_or_none()
                if existing:
                    continue

                new_bp = BlueprintModel(
                    user_id=None,
                    name=bp.name,
                    description=bp.description,
                    rules_json=[check.model_dump() for check in bp.checks],
                )
                db.add(new_bp)
                seeded += 1
            except Exception as e:
                logger.error(f"Failed to seed blueprint {json_file.name}: {e}")

        if seeded > 0:
            await db.commit()
        logger.info(f"System blueprints verified/seeded: {seeded} new, {len(json_files)} total on disk.")