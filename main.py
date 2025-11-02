#!/usr/bin/env python3
"""
Binance Futures Copy Trading Bot - Main Entry Point

This bot monitors a master Binance Futures account and automatically replicates
trades to one or more follower accounts in real-time.

Features:
- Real-time WebSocket monitoring
- Balance checking before orders (with concurrent safety)
- MIN_NOTIONAL validation (for all order types)
- Price & quantity precision handling
- Leverage management (auto-configured on startup)
- Position mode management (one-way / hedge)
- Margin type management (isolated / crossed)
- Order deduplication (timestamp-based)
- Robust time synchronization

Usage:
    python main.py [--config CONFIG_FILE]

Configuration:
    Copy config.example.yaml to config.yaml and fill in your API credentials.
"""

import sys
import signal
import argparse
import logging
from pathlib import Path

from src.config_loader import load_config
from src.logger import setup_logging
from src.futures_copy_trade_engine import FuturesCopyTradeEngine


logger = logging.getLogger(__name__)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Binance Futures Copy Trading Bot',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Use default config.yaml
  python main.py --config my.yaml   # Use custom config file

For more information, see README.md
        """
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='Binance Futures Copy Trading Bot v1.0.0'
    )
    
    return parser.parse_args()


def validate_config(config):
    """
    Validate configuration before starting.
    
    Args:
        config: Configuration object
        
    Raises:
        ValueError: If configuration is invalid
    """
    # Check for placeholder API keys
    placeholder_keys = ['YOUR_MASTER_API_KEY', 'YOUR_FOLLOWER1_API_KEY', 'YOUR_FOLLOWER2_API_KEY']
    
    if config.master.api_key in placeholder_keys:
        raise ValueError(
            "Master API key is not configured. "
            "Please edit config.yaml and add your API credentials."
        )
    
    # Check if at least one follower is enabled
    enabled_followers = [f for f in config.followers if f.enabled]
    if not enabled_followers:
        raise ValueError(
            "No follower accounts are enabled. "
            "Please enable at least one follower in config.yaml"
        )
    
    for follower in enabled_followers:
        if follower.api_key in placeholder_keys:
            raise ValueError(
                f"Follower '{follower.name}' API key is not configured. "
                f"Please edit config.yaml and add API credentials."
            )
    
    # Validate leverage
    if config.trading.leverage < 1 or config.trading.leverage > 125:
        raise ValueError(f"Invalid leverage: {config.trading.leverage}. Must be between 1-125")
    
    # Validate margin type
    if config.trading.margin_type not in ['ISOLATED', 'CROSSED']:
        raise ValueError(f"Invalid margin_type: {config.trading.margin_type}. Must be ISOLATED or CROSSED")
    
    # Validate position mode
    if config.trading.position_mode not in ['one_way', 'hedge']:
        raise ValueError(f"Invalid position_mode: {config.trading.position_mode}. Must be one_way or hedge")
    
    logger.info(f"Configuration validated: {len(enabled_followers)} follower(s) enabled")


def print_banner():
    """Print welcome banner."""
    banner = """
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     Binance Futures Copy Trading Bot v1.0.0              ║
║                                                           ║
║  Automatically replicate futures trades from master      ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """
    print(banner)


def main():
    """Main entry point."""
    args = parse_arguments()
    
    try:
        # Load configuration
        config = load_config(args.config)
        
        # Setup logging
        setup_logging(config.logging)
        
        # Print banner
        print_banner()
        
        logger.info("=" * 60)
        logger.info("Starting Binance Futures Copy Trading Bot")
        logger.info("=" * 60)
        logger.info(f"Configuration file: {args.config}")
        logger.info(f"Base URL: {config.base_url}")
        logger.info(f"Master account: {config.master.api_key[:8]}...")
        
        # Validate configuration
        validate_config(config)
        
        # Display follower information
        logger.info("-" * 60)
        logger.info("Follower Accounts:")
        for follower in config.followers:
            if follower.enabled:
                logger.info(f"  • {follower.name}: scale={follower.scale}x, "
                          f"api_key={follower.api_key[:8]}...")
        logger.info("-" * 60)
        
        # Display trading settings
        logger.info("Trading Settings:")
        logger.info(f"  • Follower order type: {config.trading.follower_order_type}")
        logger.info(f"  • Leverage: {config.trading.leverage}x")
        logger.info(f"  • Margin type: {config.trading.margin_type}")
        logger.info(f"  • Position mode: {config.trading.position_mode}")
        logger.info(f"  • Min order quantity: {config.trading.min_order_quantity}")
        logger.info(f"  • Max order quantity: {config.trading.max_order_quantity}")
        
        if config.trading.symbol_leverage:
            logger.info(f"  • Symbol-specific leverage:")
            for symbol, lev in config.trading.symbol_leverage.items():
                logger.info(f"      {symbol}: {lev}x")
        
        if config.trading.allowed_symbols:
            logger.info(f"  • Allowed symbols: {', '.join(config.trading.allowed_symbols)}")
        if config.trading.excluded_symbols:
            logger.info(f"  • Excluded symbols: {', '.join(config.trading.excluded_symbols)}")
        
        logger.info("-" * 60)
        
        # Display risk management settings
        if config.risk_management.enabled:
            logger.info("Risk Management: ENABLED")
            logger.info(f"  • Max daily trades: {config.risk_management.max_daily_trades}")
            logger.info(f"  • Max daily loss: {config.risk_management.max_daily_loss_percentage}%")
            logger.info(f"  • Max position size: {config.risk_management.max_position_size_percentage}%")
            logger.info(f"  • Min balance required: {config.risk_management.min_balance_required} USDT")
            logger.info("-" * 60)
        
        # Warning for production use
        if 'testnet' not in config.base_url:
            logger.warning("⚠️  WARNING: Using PRODUCTION environment!")
            logger.warning("⚠️  Real money will be traded. Make sure you know what you're doing!")
            logger.warning("⚠️  Futures trading involves HIGH RISK and can result in significant losses!")
            logger.warning("=" * 60)
        else:
            logger.info("Using TESTNET environment (safe for testing)")
            logger.info("=" * 60)
        
        # Initialize engine
        engine = FuturesCopyTradeEngine(config)
        
        # Setup signal handlers for graceful shutdown
        def signal_handler(sig, frame):
            logger.info("\nReceived interrupt signal, shutting down...")
            engine.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start engine
        logger.info("🚀 Starting futures copy trading engine...")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 60)
        
        engine.start()
        
        # Keep main thread alive
        while engine.is_running:
            signal.pause()
        
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}")
        print("\nPlease create a config.yaml file:")
        print("  1. Copy config.example.yaml to config.yaml")
        print("  2. Edit config.yaml and add your API credentials")
        print("  3. Run the bot again")
        sys.exit(1)
        
    except ValueError as e:
        print(f"\n❌ Configuration Error: {e}")
        sys.exit(1)
        
    except KeyboardInterrupt:
        logger.info("\nShutdown requested by user")
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
