from __future__ import annotations
from enum import Enum

class OrderEventType(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    ERROR = "ERROR"
    RECONCILED = "RECONCILED"

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class ReasonCode(str, Enum):
    # Strategy / trading
    STRATEGY_SIGNAL = "STRATEGY_SIGNAL"
    STRATEGY_EXIT = "STRATEGY_EXIT"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"

    # Admin / ops
    ADMIN_HALT = "ADMIN_HALT"
    ADMIN_RESUME = "ADMIN_RESUME"
    ADMIN_UPDATE_CONFIG = "ADMIN_UPDATE_CONFIG"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"

    # Data / system
    RECONCILE = "RECONCILE"
    DATA_SYNC = "DATA_SYNC"
    SYSTEM = "SYSTEM"

    # AI / learning
    AI_SELECT = "AI_SELECT"
    AI_TRAIN = "AI_TRAIN"
