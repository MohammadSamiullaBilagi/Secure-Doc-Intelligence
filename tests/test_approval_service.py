import pytest
from unittest.mock import MagicMock, patch
from services.approval_service import ApprovalService
from utils.exceptions import ApprovalStateError

@pytest.fixture
def mock_orchestrator():
    orchestrator = MagicMock()
    graph_mock = MagicMock()
    orchestrator.get_compiled_graph.return_value = graph_mock
    return orchestrator

def test_approve_and_resume_success(mock_orchestrator):
    # Arrange
    service = ApprovalService(mock_orchestrator)
    session_hash = "session_123"
    edited_text = "My manual edit to the contract."
    
    # Mock the state snapshot returned by LangGraph
    mock_state = MagicMock()
    mock_state.next = ('dispatch',)
    mock_state.values = {
        "remediation_draft": {"email_body": "Old text"}
    }
    service.graph.get_state.return_value = mock_state
    
    # Act
    service.approve_and_resume(session_hash, edited_text)
    
    # Assert
    # 1. Did we mutate the state with the edited text?
    expected_config = {"configurable": {"thread_id": session_hash}}
    service.graph.update_state.assert_called_once_with(
        expected_config, 
        {"remediation_draft": {"email_body": edited_text}}
    )
    
    # 2. Did we resume the graph?
    service.graph.invoke.assert_called_once_with(None, config=expected_config)

def test_approve_and_resume_fails_if_not_paused(mock_orchestrator):
    # Arrange
    service = ApprovalService(mock_orchestrator)
    
    # Mock a state that is ALREADY completed (next is empty tuple)
    mock_state = MagicMock()
    mock_state.next = tuple() 
    service.graph.get_state.return_value = mock_state
    
    # Act & Assert
    with pytest.raises(ApprovalStateError):
        service.approve_and_resume("session_123", "Some text")