"""Shared application state for the web app — thread-safe singleton."""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any

from strategy import RGCandleBreakoutStrategy


@dataclass
class AppState:
    """Thread-safe shared state between FastAPI handlers and background workers."""

    # Strategy instance
    strategy: Optional[RGCandleBreakoutStrategy] = None
    is_connected: bool = False

    # Background task control
    stop_event: threading.Event = field(default_factory=threading.Event)
    mode: str = "idle"  # idle, scanning, live, paper, backtesting

    # Real-time data
    current_price: float = 0.0
    detected_pairs: Dict[str, List] = field(default_factory=dict)
    sse_queue: List[Dict] = field(default_factory=list)

    # Runtime config overrides (settings panel)
    config_overrides: Dict[str, Any] = field(default_factory=dict)

    # Thread safety
    lock: threading.Lock = field(default_factory=threading.Lock)


app_state = AppState()
