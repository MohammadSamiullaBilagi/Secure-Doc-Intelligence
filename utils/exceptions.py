class MicroSaaSException(Exception):
    """Base exception for all domain errors."""
    pass

class ResourceNotFoundError(MicroSaaSException):
    """Raised when a session or file is missing."""
    pass

class ScrapingError(MicroSaaSException):
    """Raised when the regulatory scraper fails after retries."""
    pass

class BlueprintLoadError(MicroSaaSException):
    """Raised when a blueprint JSON is missing or invalid."""
    pass

class AgentExecutionError(MicroSaaSException):
    """Raised when a LangGraph node fails critically."""
    pass

class WebhookDeliveryError(MicroSaaSException):
    """Raised when the payload fails to deliver to the external automation platform."""
    pass

class ApprovalStateError(MicroSaaSException):
    """Raised when trying to approve/reject a thread that is not in a paused state."""
    pass