# app/models/base.py

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

db = SQLAlchemy()

class BaseModel(db.Model):
    """Base model class with common functionality"""
    __abstract__ = True
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    
    @classmethod
    def safe_create(cls, **kwargs):
        """Safely create a new record with error handling"""
        try:
            instance = cls(**kwargs)
            db.session.add(instance)
            db.session.commit()
            return instance, None
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error creating {cls.__name__}: {str(e)}")
            return None, str(e)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error creating {cls.__name__}: {str(e)}")
            return None, str(e)
    
    def safe_update(self, **kwargs):
        """Safely update record with error handling"""
        try:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)
            self.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            return True, None
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error updating {self.__class__.__name__}: {str(e)}")
            return False, str(e)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error updating {self.__class__.__name__}: {str(e)}")
            return False, str(e)
    
    def safe_delete(self):
        """Safely delete record with error handling"""
        try:
            db.session.delete(self)
            db.session.commit()
            return True, None
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error deleting {self.__class__.__name__}: {str(e)}")
            return False, str(e)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Unexpected error deleting {self.__class__.__name__}: {str(e)}")
            return False, str(e)
