#!/usr/bin/env python3
"""
Binance Copy Trading Bot - Main Entry Point

This bot monitors a master Binance account and automatically replicates trades
to one or more follower accounts in real-time.

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
from src.copy_trade_engine import CopyTradeEngine


logger = logging.getLogger(__name__)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Binance Copy Trading Bot',
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
        version='Binance Copy Trading Bot v1.0.0'
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
    
    logger.info(f"Configuration validated: {len(enabled_followers)} follower(s) enabled")


def print_banner():
    """Print welcome banner."""
    banner = """
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║        Binance Copy Trading Bot v1.0.0                    ║
║                                                           ║
║  Automatically replicate trades from master to followers  ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """
    print(banner)


def main():
    """Main entry point."""
    # Parse arguments
    args = parse_arguments()
    
    try:
        # Load configuration
        config = load_config(args.config)
        
        # Setup logging
        setup_logging(config.logging)
        
        # Print banner
        print_banner()
        
        logger.info("=" * 60)
        logger.info("Starting Binance Copy Trading Bot")
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
        logger.info(f"  • Min order quantity: {config.trading.min_order_quantity}")
        logger.info(f"  • Max order quantity: {config.trading.max_order_quantity}")
        
        if config.trading.allowed_symbols:
            logger.info(f"  • Allowed symbols: {', '.join(config.trading.allowed_symbols)}")
        if config.trading.excluded_symbols:
            logger.info(f"  • Excluded symbols: {', '.join(config.trading.excluded_symbols)}")
        
        logger.info("=" * 60)
        
        # Warning for production use
        if 'testnet' not in config.base_url:
            logger.warning("⚠️  WARNING: Using PRODUCTION environment!")
            logger.warning("⚠️  Real money will be traded. Make sure you know what you're doing!")
            logger.warning("=" * 60)
        else:
            logger.info("Using TESTNET environment (safe for testing)")
            logger.info("=" * 60)
        
        # Initialize engine
        engine = CopyTradeEngine(config)
        
        # Setup signal handlers for graceful shutdown
        def signal_handler(sig, frame):
            logger.info("\nReceived interrupt signal, shutting down...")
            engine.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start engine
        logger.info("🚀 Starting copy trading engine...")
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
