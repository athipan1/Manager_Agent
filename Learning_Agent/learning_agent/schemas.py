
from sqlalchemy import Column, String, Float, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class BiasState(Base):
    """
    SQLAlchemy model for persisting the BIAS_STATE of each asset.
    """
    __tablename__ = 'bias_states'

    asset_id = Column(String, primary_key=True, index=True)
    bull_bias = Column(Float, nullable=False, default=0.0)
    bear_bias = Column(Float, nullable=False, default=0.0)
    vol_bias = Column(Float, nullable=False, default=0.0)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "bull_bias": self.bull_bias,
            "bear_bias": self.bear_bias,
            "vol_bias": self.vol_bias
        }
