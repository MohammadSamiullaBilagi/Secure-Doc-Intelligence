import json
import logging
from pathlib import Path
from schemas.blueprint_schema import Blueprint
from utils.exceptions import BlueprintLoadError

logger = logging.getLogger(__name__)

class BlueprintService:
    BLUEPRINT_DIR = Path("blueprints")

    @classmethod
    def load_blueprint(cls, blueprint_filename: str) -> Blueprint:
        """Loads and strictly validates a JSON blueprint."""
        file_path = cls.BLUEPRINT_DIR / blueprint_filename
        
        if not file_path.exists():
            logger.error(f"Blueprint not found: {file_path}")
            raise BlueprintLoadError(f"Blueprint '{blueprint_filename}' does not exist.")
            
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