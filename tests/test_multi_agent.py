import pytest
from unittest.mock import patch, MagicMock
from schemas.blueprint_schema import Blueprint, BlueprintCheck
from multi_agent import ComplianceOrchestrator

@pytest.fixture
def mock_blueprint():
    return Blueprint(
        blueprint_id="TEST_01",
        name="Test Blueprint",
        description="Testing suite",
        checks=[
            BlueprintCheck(check_id="C1", focus="Find liability.", rule="Liability must be capped.")
        ]
    )

@patch('multi_agent.SecureDocAgent')
@patch('multi_agent.ChatOpenAI')
def test_researcher_node(MockChat, MockDocAgent, mock_blueprint):
    # Arrange
    # Mock the DocAgent to return a specific answer
    mock_agent_instance = MagicMock()
    mock_agent_instance.query.return_value = {"answer": "Liability is unlimited."}
    MockDocAgent.return_value = mock_agent_instance
    
    orchestrator = ComplianceOrchestrator(db_dir="dummy_path")
    
    state = {
        "target_contract": "contract.pdf",
        "blueprint": mock_blueprint,
        "extracted_clauses": {},
        "audit_results": [],
        "status": ""
    }
    
    # Act
    result_state = orchestrator.researcher_node(state)
    
    # Assert
    assert "C1" in result_state["extracted_clauses"]
    assert result_state["extracted_clauses"]["C1"] == "Liability is unlimited."
    mock_agent_instance.query.assert_called_once_with("Find liability.", metadata_filter={"source": "contract.pdf"})