"""Configuration loader for Binance copy trading bot."""

import os
import yaml
from typing import Dict, List, Any
from dataclasses import dataclass


@dataclass
class MasterConfig:
    """Master account configuration."""
    api_key: str
    api_secret: str


@dataclass
class FollowerConfig:
    """Follower account configuration."""
    name: str
    api_key: str
    api_secret: str
    scale: float
    enabled: bool


@dataclass
class TradingConfig:
    """Trading settings configuration."""
    follower_order_type: str
    min_order_quantity: float
    max_order_quantity: float
    allowed_symbols: List[str]
    excluded_symbols: List[str]
    # Futures specific
    leverage: int = 10
    margin_type: str = 'CROSSED'
    position_mode: str = 'one_way'
    auto_set_leverage: bool = True
    symbol_leverage: Dict[str, int] = None
    
    def __post_init__(self):
        if self.symbol_leverage is None:
            self.symbol_leverage = {}
    
    def get(self, key: str, default=None):
        """Get attribute by key name."""
        return getattr(self, key, default)


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str
    file: str
    max_bytes: int
    backup_count: int
    console_output: bool


@dataclass
class WebSocketConfig:
    """WebSocket configuration."""
    reconnect_enabled: bool
    reconnect_delay: int
    max_reconnect_attempts: int
    keepalive_interval: int


@dataclass
class RiskManagementConfig:
    """Risk management configuration."""
    enabled: bool
    max_daily_trades: int
    max_daily_loss_percentage: float
    max_position_size_percentage: float
    min_balance_required: float = 10.0
    emergency_stop_percentage: float = 50.0


@dataclass
class Config:
    """Main configuration container."""
    base_url: str
    master: MasterConfig
    followers: List[FollowerConfig]
    trading: TradingConfig
    logging: LoggingConfig
    websocket: WebSocketConfig
    risk_management: RiskManagementConfig


def load_config(config_path: str = "config.yaml") -> Config:
    """
    Load configuration from YAML file.
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        Config object with all settings
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            f"Please copy config.example.yaml to config.yaml and fill in your API credentials."
        )
    
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    if not data:
        raise ValueError("Configuration file is empty")
    
    # Validate required fields
    required_fields = ['base_url', 'master', 'followers']
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field in config: {field}")
    
    # Parse master config
    master_data = data['master']
    master = MasterConfig(
        api_key=master_data['api_key'],
        api_secret=master_data['api_secret']
    )
    
    # Parse followers config
    followers = []
    for follower_data in data.get('followers', []):
        follower = FollowerConfig(
            name=follower_data['name'],
            api_key=follower_data['api_key'],
            api_secret=follower_data['api_secret'],
            scale=follower_data.get('scale', 1.0),
            enabled=follower_data.get('enabled', True)
        )
        followers.append(follower)
    
    # Parse trading config
    trading_data = data.get('trading', {})
    trading = TradingConfig(
        follower_order_type=trading_data.get('follower_order_type', 'MARKET'),
        min_order_quantity=trading_data.get('min_order_quantity', 0.001),
        max_order_quantity=trading_data.get('max_order_quantity', 1000.0),
        allowed_symbols=trading_data.get('allowed_symbols', []),
        excluded_symbols=trading_data.get('excluded_symbols', []),
        leverage=trading_data.get('leverage', 10),
        margin_type=trading_data.get('margin_type', 'CROSSED'),
        position_mode=trading_data.get('position_mode', 'one_way'),
        auto_set_leverage=trading_data.get('auto_set_leverage', True),
        symbol_leverage=trading_data.get('symbol_leverage', {})
    )
    
    # Parse logging config
    logging_data = data.get('logging', {})
    logging_config = LoggingConfig(
        level=logging_data.get('level', 'INFO'),
        file=logging_data.get('file', 'logs/copy_trade.log'),
        max_bytes=logging_data.get('max_bytes', 10485760),
        backup_count=logging_data.get('backup_count', 5),
        console_output=logging_data.get('console_output', True)
    )
    
    # Parse websocket config
    ws_data = data.get('websocket', {})
    websocket = WebSocketConfig(
        reconnect_enabled=ws_data.get('reconnect_enabled', True),
        reconnect_delay=ws_data.get('reconnect_delay', 5),
        max_reconnect_attempts=ws_data.get('max_reconnect_attempts', 10),
        keepalive_interval=ws_data.get('keepalive_interval', 1800)
    )
    
    # Parse risk management config
    risk_data = data.get('risk_management', {})
    risk_management = RiskManagementConfig(
        enabled=risk_data.get('enabled', False),
        max_daily_trades=risk_data.get('max_daily_trades', 100),
        max_daily_loss_percentage=risk_data.get('max_daily_loss_percentage', 5.0),
        max_position_size_percentage=risk_data.get('max_position_size_percentage', 10.0),
        min_balance_required=risk_data.get('min_balance_required', 10.0),
        emergency_stop_percentage=risk_data.get('emergency_stop_percentage', 50.0)
    )
    
    return Config(
        base_url=data['base_url'],
        master=master,
        followers=followers,
        trading=trading,
        logging=logging_config,
        websocket=websocket,
        risk_management=risk_management
    )
