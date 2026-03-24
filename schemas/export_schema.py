import enum


class ExportFormat(str, enum.Enum):
    CSV = "csv"
    TALLY = "tally"
    ZOHO = "zoho"
