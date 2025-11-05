import pytest
import os
from unittest.mock import patch, MagicMock
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError
from flask_app.models.base import BaseModel, db
from datetime import datetime, timezone


class TestModel(BaseModel):
    """Test model for testing BaseModel functionality"""
    __tablename__ = 'test_models'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Integer, default=0)


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test_secret_key'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Mock logger to prevent actual logging during tests
    app.logger = MagicMock()
    
    db.init_app(app)
    
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def test_model(app):
    """Create a test model instance"""
    with app.app_context():
        model = TestModel(name='test', value=42)
        db.session.add(model)
        db.session.commit()
        # Refresh the model to ensure it's properly attached to the session
        db.session.refresh(model)
        return model


class TestBaseModel:
    """Comprehensive tests for BaseModel class"""

    def test_model_creation(self, app):
        """Test basic model creation"""
        with app.app_context():
            model = TestModel(name='test', value=42)
            assert model.name == 'test'
            assert model.value == 42
            # Timestamps are set when the model is committed to the database
            db.session.add(model)
            db.session.commit()
            assert model.created_at is not None
            assert model.updated_at is not None

    def test_created_at_auto_set(self, app):
        """Test that created_at is automatically set"""
        with app.app_context():
            before_creation = datetime.now(timezone.utc)
            model = TestModel(name='test')
            db.session.add(model)
            db.session.commit()
            after_creation = datetime.now(timezone.utc)
            
            # Make sure model.created_at is timezone-aware for comparison
            if model.created_at.tzinfo is None:
                model.created_at = model.created_at.replace(tzinfo=timezone.utc)
            
            assert before_creation <= model.created_at <= after_creation
            assert model.created_at.tzinfo is not None

    def test_updated_at_auto_set(self, app):
        """Test that updated_at is automatically set"""
        with app.app_context():
            before_creation = datetime.now(timezone.utc)
            model = TestModel(name='test')
            db.session.add(model)
            db.session.commit()
            after_creation = datetime.now(timezone.utc)
            
            # Make sure model.updated_at is timezone-aware for comparison
            if model.updated_at.tzinfo is None:
                model.updated_at = model.updated_at.replace(tzinfo=timezone.utc)
            
            assert before_creation <= model.updated_at <= after_creation
            assert model.updated_at.tzinfo is not None

    def test_updated_at_on_update(self, app, test_model):
        """Test that updated_at is updated when model is modified"""
        with app.app_context():
            # Ensure the model is in the session
            db.session.add(test_model)
            db.session.commit()
            
            original_updated_at = test_model.updated_at
            
            # Wait a small amount to ensure time difference
            import time
            time.sleep(0.1)  # Increased sleep time
            
            test_model.value = 100
            db.session.commit()
            
            # Refresh the model to get updated timestamp
            db.session.refresh(test_model)
            
            # Make sure both timestamps are timezone-aware for comparison
            if test_model.updated_at.tzinfo is None:
                test_model.updated_at = test_model.updated_at.replace(tzinfo=timezone.utc)
            if original_updated_at.tzinfo is None:
                original_updated_at = original_updated_at.replace(tzinfo=timezone.utc)
            
            assert test_model.updated_at > original_updated_at

    def test_safe_create_success(self, app):
        """Test successful safe_create"""
        with app.app_context():
            instance, error = TestModel.safe_create(name='test', value=42)
            
            assert instance is not None
            assert error is None
            assert instance.name == 'test'
            assert instance.value == 42
            assert instance.id is not None

    def test_safe_create_database_error(self, app):
        """Test safe_create with database error"""
        with app.app_context():
            with patch('flask_app.models.base.db.session.commit', side_effect=SQLAlchemyError("Database error")):
                instance, error = TestModel.safe_create(name='test', value=42)
                
                assert instance is None
                assert error == "Database error"
                app.logger.error.assert_called_once()
                assert "Database error creating TestModel" in app.logger.error.call_args[0][0]

    def test_safe_create_unexpected_error(self, app):
        """Test safe_create with unexpected error"""
        with app.app_context():
            with patch('flask_app.models.base.db.session.commit', side_effect=ValueError("Unexpected error")):
                instance, error = TestModel.safe_create(name='test', value=42)
                
                assert instance is None
                assert error == "Unexpected error"
                app.logger.error.assert_called_once()
                assert "Unexpected error creating TestModel" in app.logger.error.call_args[0][0]

    def test_safe_create_rollback_on_error(self, app):
        """Test that safe_create rolls back on error"""
        with app.app_context():
            with patch('flask_app.models.base.db.session.commit', side_effect=SQLAlchemyError("Database error")):
                with patch('flask_app.models.base.db.session.rollback') as mock_rollback:
                    TestModel.safe_create(name='test', value=42)
                    mock_rollback.assert_called_once()

    def test_safe_update_success(self, app, test_model):
        """Test successful safe_update"""
        with app.app_context():
            success, error = test_model.safe_update(name='updated', value=100)
            
            assert success is True
            assert error is None
            assert test_model.name == 'updated'
            assert test_model.value == 100
            assert test_model.updated_at is not None

    def test_safe_update_with_invalid_attribute(self, app, test_model):
        """Test safe_update with invalid attribute"""
        with app.app_context():
            original_name = test_model.name
            success, error = test_model.safe_update(invalid_attr='value', name='updated')
            
            assert success is True
            assert error is None
            assert test_model.name == 'updated'  # Valid attribute updated
            assert not hasattr(test_model, 'invalid_attr')  # Invalid attribute ignored

    def test_safe_update_database_error(self, app, test_model):
        """Test safe_update with database error"""
        with app.app_context():
            with patch('flask_app.models.base.db.session.commit', side_effect=SQLAlchemyError("Database error")):
                success, error = test_model.safe_update(name='updated')
                
                assert success is False
                assert error == "Database error"
                app.logger.error.assert_called_once()
                assert "Database error updating TestModel" in app.logger.error.call_args[0][0]

    def test_safe_update_unexpected_error(self, app, test_model):
        """Test safe_update with unexpected error"""
        with app.app_context():
            with patch('flask_app.models.base.db.session.commit', side_effect=ValueError("Unexpected error")):
                success, error = test_model.safe_update(name='updated')
                
                assert success is False
                assert error == "Unexpected error"
                app.logger.error.assert_called_once()
                assert "Unexpected error updating TestModel" in app.logger.error.call_args[0][0]

    def test_safe_update_rollback_on_error(self, app, test_model):
        """Test that safe_update rolls back on error"""
        with app.app_context():
            with patch('flask_app.models.base.db.session.commit', side_effect=SQLAlchemyError("Database error")):
                with patch('flask_app.models.base.db.session.rollback') as mock_rollback:
                    test_model.safe_update(name='updated')
                    mock_rollback.assert_called_once()

    def test_safe_update_updates_timestamp(self, app, test_model):
        """Test that safe_update updates the timestamp"""
        with app.app_context():
            # Ensure the model is in the session
            db.session.add(test_model)
            db.session.commit()
            
            original_updated_at = test_model.updated_at
            
            # Wait a small amount to ensure time difference
            import time
            time.sleep(0.1)  # Increased sleep time
            
            success, error = test_model.safe_update(value=999)
            
            assert success is True
            # Refresh to get updated timestamp
            db.session.refresh(test_model)
            
            # Make sure both timestamps are timezone-aware for comparison
            if test_model.updated_at.tzinfo is None:
                test_model.updated_at = test_model.updated_at.replace(tzinfo=timezone.utc)
            if original_updated_at.tzinfo is None:
                original_updated_at = original_updated_at.replace(tzinfo=timezone.utc)
            
            assert test_model.updated_at > original_updated_at

    def test_safe_delete_success(self, app, test_model):
        """Test successful safe_delete"""
        with app.app_context():
            model_id = test_model.id
            success, error = test_model.safe_delete()
            
            assert success is True
            assert error is None
            
            # Verify model is deleted
            deleted_model = db.session.get(TestModel, model_id)
            assert deleted_model is None

    def test_safe_delete_database_error(self, app, test_model):
        """Test safe_delete with database error"""
        with app.app_context():
            with patch('flask_app.models.base.db.session.commit', side_effect=SQLAlchemyError("Database error")):
                success, error = test_model.safe_delete()
                
                assert success is False
                assert error == "Database error"
                app.logger.error.assert_called_once()
                assert "Database error deleting TestModel" in app.logger.error.call_args[0][0]

    def test_safe_delete_unexpected_error(self, app, test_model):
        """Test safe_delete with unexpected error"""
        with app.app_context():
            with patch('flask_app.models.base.db.session.commit', side_effect=ValueError("Unexpected error")):
                success, error = test_model.safe_delete()
                
                assert success is False
                assert error == "Unexpected error"
                app.logger.error.assert_called_once()
                assert "Unexpected error deleting TestModel" in app.logger.error.call_args[0][0]

    def test_safe_delete_rollback_on_error(self, app, test_model):
        """Test that safe_delete rolls back on error"""
        with app.app_context():
            with patch('flask_app.models.base.db.session.commit', side_effect=SQLAlchemyError("Database error")):
                with patch('flask_app.models.base.db.session.rollback') as mock_rollback:
                    test_model.safe_delete()
                    mock_rollback.assert_called_once()

    def test_safe_delete_preserves_model_on_error(self, app, test_model):
        """Test that safe_delete preserves model when error occurs"""
        with app.app_context():
            model_id = test_model.id
            with patch('flask_app.models.base.db.session.commit', side_effect=SQLAlchemyError("Database error")):
                success, error = test_model.safe_delete()
                
                assert success is False
                # Model should still exist
                preserved_model = db.session.get(TestModel, model_id)
                assert preserved_model is not None
                assert preserved_model.id == model_id

    def test_multiple_safe_operations(self, app):
        """Test multiple safe operations in sequence"""
        with app.app_context():
            # Create
            instance, error = TestModel.safe_create(name='test1', value=1)
            assert instance is not None
            assert error is None
            
            # Update
            success, error = instance.safe_update(name='test1_updated', value=2)
            assert success is True
            assert error is None
            assert instance.name == 'test1_updated'
            assert instance.value == 2
            
            # Delete
            success, error = instance.safe_delete()
            assert success is True
            assert error is None

    def test_safe_create_with_none_values(self, app):
        """Test safe_create with None values"""
        with app.app_context():
            # TestModel requires name to be not None, so we'll test with valid name and None value
            # Note: value has a default of 0, so None will be converted to 0
            instance, error = TestModel.safe_create(name='test', value=None)
            
            assert instance is not None
            assert error is None
            assert instance.name == 'test'
            assert instance.value == 0  # Default value when None is passed

    def test_safe_update_with_empty_kwargs(self, app, test_model):
        """Test safe_update with empty kwargs"""
        with app.app_context():
            original_name = test_model.name
            original_value = test_model.value
            
            success, error = test_model.safe_update()
            
            assert success is True
            assert error is None
            assert test_model.name == original_name
            assert test_model.value == original_value
            # updated_at should still be updated
            assert test_model.updated_at is not None

    def test_safe_operations_with_current_app_context(self, app):
        """Test that safe operations work with current_app context"""
        with app.app_context():
            # Test that current_app.logger is used
            with patch('flask_app.models.base.current_app.logger') as mock_logger:
                with patch('flask_app.models.base.db.session.commit', side_effect=SQLAlchemyError("Test error")):
                    TestModel.safe_create(name='test')
                    mock_logger.error.assert_called_once()
                    assert "Database error creating TestModel" in mock_logger.error.call_args[0][0]
