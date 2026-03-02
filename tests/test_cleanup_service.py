import pytest
from unittest.mock import patch, MagicMock
from services.cleanup_service import CleanupService

@patch('services.cleanup_service.SessionLocal')
@patch('services.cleanup_service.shutil.rmtree')
def test_sweep_stale_sessions(mock_rmtree, mock_db_session):
    # Arrange
    mock_db = MagicMock()
    mock_db_session.return_value = mock_db
    
    mock_repo = MagicMock()
    mock_expired_session = MagicMock()
    mock_expired_session.session_hash = "test_hash_123"
    mock_repo.get_expired_sessions.return_value = [mock_expired_session]
    
    with patch('services.cleanup_service.SessionRepository', return_value=mock_repo):
        # Act
        with patch('pathlib.Path.exists', return_value=True):
            CleanupService.sweep_stale_sessions()
            
        # Assert
        mock_repo.get_expired_sessions.assert_called_once()
        mock_rmtree.assert_called_once() # Ensures disk wipe was triggered
        mock_repo.mark_deleted.assert_called_once_with("test_hash_123")