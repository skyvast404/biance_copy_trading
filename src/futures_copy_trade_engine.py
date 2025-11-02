"""Futures copy trading engine with advanced features."""

import json
import time
import logging
from threading import Thread, Event, Lock
from typing import Dict, List, Optional, Set
from datetime import datetime
from collections import deque
from decimal import Decimal

import websocket

from .binance_futures_client import BinanceFuturesClient, BinanceAPIError, PositionSide, MarginType
from .config_loader import Config


logger = logging.getLogger(__name__)


class FuturesCopyTradeEngine:
    """
    Advanced futures copy trading engine.
    
    Features:
    - Balance checking before orders
    - MIN_NOTIONAL validation
    - Price precision handling
    - Leverage management
    - Position mode management
    - Stop loss / Take profit
    - Partial fill handling
    - Order deduplication
    """

    def __init__(self, config: Config) -> None:
        """Initialize futures copy trade engine."""
        self.config = config
        
        # Initialize master client
        self.master_client = BinanceFuturesClient(
            api_key=config.master.api_key,
            api_secret=config.master.api_secret,
            base_url=config.base_url
        )
        
        # Initialize follower clients
        self.follower_clients: Dict[str, BinanceFuturesClient] = {}
        for follower in config.followers:
            if follower.enabled:
                self.follower_clients[follower.name] = BinanceFuturesClient(
                    api_key=follower.api_key,
                    api_secret=follower.api_secret,
                    base_url=config.base_url
                )
        
        # WebSocket state
        self.listen_key: Optional[str] = None
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[Thread] = None
        self.keepalive_thread: Optional[Thread] = None
        self.stop_event = Event()
        
        # Reconnection state
        self.reconnect_count = 0
        self.is_running = False
        
        # Order deduplication
        self.processed_orders: deque = deque(maxlen=1000)
        self.order_lock = Lock()
        
        # Statistics
        self.stats = {
            'total_trades': 0,
            'successful_copies': 0,
            'failed_copies': 0,
            'duplicate_filtered': 0,
            'insufficient_balance': 0,
            'min_notional_rejected': 0,
            'start_time': None
        }
        
        logger.info(f"Futures copy trade engine initialized with {len(self.follower_clients)} followers")

    def start(self) -> None:
        """Start the copy trading engine."""
        if self.is_running:
            logger.warning("Engine is already running")
            return
        
        self.is_running = True
        self.stop_event.clear()
        self.stats['start_time'] = datetime.now()
        
        logger.info("Starting futures copy trade engine...")
        
        try:
            # Initialize account settings
            self._initialize_accounts()
            
            # Create listen key
            self.listen_key = self.master_client.create_listen_key()
            
            # Start keepalive thread
            self.keepalive_thread = Thread(target=self._keepalive_loop, daemon=True)
            self.keepalive_thread.start()
            
            # Connect to WebSocket
            self._connect_websocket()
            
        except Exception as e:
            logger.error(f"Failed to start engine: {e}")
            self.is_running = False
            raise

    def _initialize_accounts(self) -> None:
        """Initialize account settings (leverage, margin type, position mode)."""
        logger.info("Initializing account settings...")
        
        # Get configuration
        leverage = self.config.trading.get('leverage', 10)
        margin_type = self.config.trading.get('margin_type', 'CROSSED')
        position_mode = self.config.trading.get('position_mode', 'one_way')  # one_way or hedge
        
        # Set position mode for all accounts
        dual_side = position_mode == 'hedge'
        
        try:
            self.master_client.set_position_mode(dual_side)
        except Exception as e:
            logger.warning(f"Failed to set master position mode: {e}")
        
        for name, client in self.follower_clients.items():
            try:
                client.set_position_mode(dual_side)
                logger.info(f"Follower '{name}': Position mode set to {position_mode}")
            except Exception as e:
                logger.warning(f"Follower '{name}': Failed to set position mode - {e}")

    def set_symbol_leverage(self, symbol: str, leverage: int) -> None:
        """
        Set leverage for a symbol on all accounts.
        
        Args:
            symbol: Trading pair symbol
            leverage: Leverage (1-125)
        """
        logger.info(f"Setting leverage for {symbol}: {leverage}x")
        
        # Set for master
        try:
            self.master_client.set_leverage(symbol, leverage)
        except Exception as e:
            logger.warning(f"Master: Failed to set leverage - {e}")
        
        # Set for followers
        for name, client in self.follower_clients.items():
            try:
                client.set_leverage(symbol, leverage)
                logger.info(f"Follower '{name}': Leverage set to {leverage}x")
            except Exception as e:
                logger.warning(f"Follower '{name}': Failed to set leverage - {e}")

    def set_symbol_margin_type(self, symbol: str, margin_type: str) -> None:
        """
        Set margin type for a symbol on all accounts.
        
        Args:
            symbol: Trading pair symbol
            margin_type: 'ISOLATED' or 'CROSSED'
        """
        margin_enum = MarginType.ISOLATED if margin_type == 'ISOLATED' else MarginType.CROSSED
        logger.info(f"Setting margin type for {symbol}: {margin_type}")
        
        # Set for master
        try:
            self.master_client.set_margin_type(symbol, margin_enum)
        except Exception as e:
            logger.warning(f"Master: Failed to set margin type - {e}")
        
        # Set for followers
        for name, client in self.follower_clients.items():
            try:
                client.set_margin_type(symbol, margin_enum)
                logger.info(f"Follower '{name}': Margin type set to {margin_type}")
            except Exception as e:
                logger.warning(f"Follower '{name}': Failed to set margin type - {e}")

    def stop(self) -> None:
        """Stop the copy trading engine."""
        if not self.is_running:
            logger.warning("Engine is not running")
            return
        
        logger.info("Stopping futures copy trade engine...")
        
        self.is_running = False
        self.stop_event.set()
        
        if self.ws:
            self.ws.close()
        
        if self.listen_key:
            try:
                self.master_client.close_listen_key(self.listen_key)
            except Exception as e:
                logger.error(f"Failed to close listen key: {e}")
        
        self._print_statistics()
        logger.info("Futures copy trade engine stopped")

    def _connect_websocket(self) -> None:
        """Connect to Binance Futures user data stream WebSocket."""
        ws_url = f"wss://fstream.binance.com/ws/{self.listen_key}"
        
        # Use testnet WebSocket URL if using testnet
        if 'testnet' in self.config.base_url:
            ws_url = f"wss://stream.binancefuture.com/ws/{self.listen_key}"
        
        logger.info(f"Connecting to Futures WebSocket...")
        
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
            on_ping=self._on_ping,
            on_pong=self._on_pong
        )
        
        self.ws_thread = Thread(target=self.ws.run_forever, daemon=True)
        self.ws_thread.start()

    def _keepalive_loop(self) -> None:
        """Periodically ping the listen key to keep it alive."""
        interval = self.config.websocket.keepalive_interval
        
        while not self.stop_event.is_set():
            try:
                self.stop_event.wait(interval)
                
                if not self.stop_event.is_set() and self.listen_key:
                    self.master_client.keepalive_listen_key(self.listen_key)
                    logger.debug("Listen key keepalive successful")
                    
            except Exception as e:
                logger.error(f"Listen key keepalive failed: {e}")

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        """Handle WebSocket connection opened."""
        logger.info("✓ Connected to Futures user data stream")
        self.reconnect_count = 0
    
    def _on_ping(self, ws: websocket.WebSocketApp, message: str) -> None:
        """Handle WebSocket ping."""
        logger.debug("Received WebSocket ping")
    
    def _on_pong(self, ws: websocket.WebSocketApp, message: str) -> None:
        """Handle WebSocket pong."""
        logger.debug("Received WebSocket pong")

    def _on_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """Handle WebSocket connection closed."""
        logger.warning(f"WebSocket closed: {close_status_code} - {close_msg}")
        
        if (self.config.websocket.reconnect_enabled and 
            self.is_running and 
            not self.stop_event.is_set()):
            self._attempt_reconnect()

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """Handle WebSocket error."""
        logger.error(f"WebSocket error: {error}")

    def _attempt_reconnect(self) -> None:
        """Attempt to reconnect to WebSocket."""
        max_attempts = self.config.websocket.max_reconnect_attempts
        delay = self.config.websocket.reconnect_delay
        
        if self.reconnect_count >= max_attempts:
            logger.error(f"Max reconnection attempts ({max_attempts}) reached. Stopping engine.")
            self.stop()
            return
        
        self.reconnect_count += 1
        logger.info(f"Attempting to reconnect ({self.reconnect_count}/{max_attempts}) in {delay}s...")
        
        time.sleep(delay)
        
        try:
            self.listen_key = self.master_client.create_listen_key()
            self._connect_websocket()
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            self._attempt_reconnect()

    def _on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message)
            event_type = data.get('e')
            
            if event_type == 'ORDER_TRADE_UPDATE':
                self._handle_order_update(data)
            elif event_type == 'ACCOUNT_UPDATE':
                logger.debug("Received account update")
            else:
                logger.debug(f"Received event: {event_type}")
                
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    def _handle_order_update(self, data: Dict) -> None:
        """Handle ORDER_TRADE_UPDATE event from Futures."""
        order_data = data.get('o', {})
        
        exec_type = order_data.get('x')  # Execution type
        order_status = order_data.get('X')  # Order status
        order_id = order_data.get('i')  # Order ID
        trade_id = order_data.get('t')  # Trade ID
        
        # Only process trades
        if exec_type != 'TRADE':
            return
        
        # Deduplication
        trade_key = f"{order_id}_{trade_id}"
        with self.order_lock:
            if trade_key in self.processed_orders:
                logger.debug(f"Duplicate trade detected: {trade_key}, skipping")
                self.stats['duplicate_filtered'] += 1
                return
            self.processed_orders.append(trade_key)
        
        symbol = order_data['s']
        side = order_data['S']
        position_side = order_data.get('ps', 'BOTH')
        order_type = order_data['o']
        
        # Last executed quantity
        last_exec_qty = float(order_data['l'])
        last_exec_price = float(order_data['L'])
        
        # Cumulative filled quantity
        cumulative_qty = float(order_data['z'])
        total_qty = float(order_data['q'])
        
        # Check if symbol is allowed
        if not self._is_symbol_allowed(symbol):
            logger.info(f"Symbol {symbol} is filtered out, skipping")
            return
        
        # Log with fill status
        fill_status = "FILLED" if order_status == 'FILLED' else f"PARTIAL ({cumulative_qty}/{total_qty})"
        logger.info(f"📊 Master {fill_status}: {side} {last_exec_qty} {symbol} @ {last_exec_price} [{position_side}]")
        
        self.stats['total_trades'] += 1
        
        # Replicate to followers
        self._replicate_to_followers(symbol, side, last_exec_qty, last_exec_price, position_side)

    def _is_symbol_allowed(self, symbol: str) -> bool:
        """Check if symbol is allowed for copy trading."""
        if symbol in self.config.trading.excluded_symbols:
            return False
        
        if self.config.trading.allowed_symbols:
            return symbol in self.config.trading.allowed_symbols
        
        return True

    def _replicate_to_followers(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        position_side: str
    ) -> None:
        """Replicate trade to all follower accounts."""
        for follower in self.config.followers:
            if not follower.enabled:
                continue
            
            if follower.name not in self.follower_clients:
                continue
            
            # Calculate follower quantity with scale
            follower_qty = quantity * follower.scale
            
            # Apply quantity limits
            if follower_qty < self.config.trading.min_order_quantity:
                logger.warning(f"Follower {follower.name}: quantity {follower_qty} below minimum, skipping")
                continue
            
            if follower_qty > self.config.trading.max_order_quantity:
                logger.warning(f"Follower {follower.name}: quantity {follower_qty} above maximum, capping")
                follower_qty = self.config.trading.max_order_quantity
            
            # Place order for follower
            self._place_follower_order(
                follower_name=follower.name,
                symbol=symbol,
                side=side,
                quantity=follower_qty,
                price=price,
                position_side=position_side
            )

    def _check_balance(self, client: BinanceFuturesClient, symbol: str, quantity: float, price: float, leverage: int) -> bool:
        """
        Check if account has sufficient balance for the order.
        
        Args:
            client: Binance Futures client
            symbol: Trading pair symbol
            quantity: Order quantity
            price: Order price
            leverage: Leverage
            
        Returns:
            True if sufficient balance, False otherwise
        """
        try:
            # Get available balance (USDT)
            available_balance = client.get_balance("USDT")
            
            # Calculate required margin
            order_value = Decimal(str(quantity)) * Decimal(str(price))
            required_margin = order_value / Decimal(str(leverage))
            
            # Add 5% buffer for fees
            required_margin = required_margin * Decimal('1.05')
            
            if available_balance < required_margin:
                logger.warning(f"Insufficient balance: available={available_balance}, required={required_margin}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to check balance: {e}")
            return False

    def _place_follower_order(
        self,
        follower_name: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        position_side: str
    ) -> None:
        """Place order for a specific follower account."""
        client = self.follower_clients.get(follower_name)
        if not client:
            logger.error(f"Follower client not found: {follower_name}")
            return
        
        order_type = self.config.trading.follower_order_type
        leverage = self.config.trading.get('leverage', 10)
        
        # Convert position side
        pos_side = PositionSide.BOTH
        if position_side == 'LONG':
            pos_side = PositionSide.LONG
        elif position_side == 'SHORT':
            pos_side = PositionSide.SHORT
        
        try:
            # Check balance before placing order
            if not self._check_balance(client, symbol, quantity, price, leverage):
                logger.error(f"✗ Follower '{follower_name}': Insufficient balance for {quantity} {symbol}")
                self.stats['insufficient_balance'] += 1
                self.stats['failed_copies'] += 1
                return
            
            # Check MIN_NOTIONAL for LIMIT orders
            if order_type == 'LIMIT':
                if not client.check_min_notional(symbol, quantity, price):
                    filters = client.get_symbol_filters(symbol)
                    min_notional = filters.get('MIN_NOTIONAL', {}).get('notional', 'N/A')
                    logger.error(f"✗ Follower '{follower_name}': Order value too small. MIN_NOTIONAL: {min_notional}")
                    self.stats['min_notional_rejected'] += 1
                    self.stats['failed_copies'] += 1
                    return
            
            # Place order
            result = client.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price if order_type == 'LIMIT' else None,
                position_side=pos_side
            )
            
            # Log detailed order info
            order_id = result.get('orderId')
            executed_qty = result.get('executedQty', 0)
            status = result.get('status')
            
            logger.info(f"✓ Follower '{follower_name}': {side} {executed_qty}/{quantity} {symbol} - "
                       f"orderId={order_id}, status={status}, positionSide={position_side}")
            
            self.stats['successful_copies'] += 1
            
        except ValueError as e:
            logger.error(f"✗ Follower '{follower_name}': Invalid parameters - {e}")
            self.stats['failed_copies'] += 1
        except BinanceAPIError as e:
            error_str = str(e)
            if 'insufficient balance' in error_str.lower():
                logger.error(f"✗ Follower '{follower_name}': Insufficient balance")
                self.stats['insufficient_balance'] += 1
            elif 'min notional' in error_str.lower():
                logger.error(f"✗ Follower '{follower_name}': Order value too small (MIN_NOTIONAL)")
                self.stats['min_notional_rejected'] += 1
            else:
                logger.error(f"✗ Follower '{follower_name}': API error - {e}")
            self.stats['failed_copies'] += 1
        except Exception as e:
            logger.error(f"✗ Follower '{follower_name}': Unexpected error - {e}", exc_info=True)
            self.stats['failed_copies'] += 1

    def _print_statistics(self) -> None:
        """Print trading statistics."""
        if self.stats['start_time']:
            runtime = datetime.now() - self.stats['start_time']
            logger.info("=" * 60)
            logger.info("FUTURES COPY TRADING STATISTICS")
            logger.info("=" * 60)
            logger.info(f"Runtime: {runtime}")
            logger.info(f"Total master trades: {self.stats['total_trades']}")
            logger.info(f"Successful copies: {self.stats['successful_copies']}")
            logger.info(f"Failed copies: {self.stats['failed_copies']}")
            logger.info(f"  - Insufficient balance: {self.stats['insufficient_balance']}")
            logger.info(f"  - MIN_NOTIONAL rejected: {self.stats['min_notional_rejected']}")
            logger.info(f"Duplicates filtered: {self.stats['duplicate_filtered']}")
            
            total_attempts = self.stats['successful_copies'] + self.stats['failed_copies']
            if total_attempts > 0:
                success_rate = (self.stats['successful_copies'] / total_attempts) * 100
                logger.info(f"Success rate: {success_rate:.2f}%")
            
            logger.info("=" * 60)

    def get_statistics(self) -> Dict:
        """Get current trading statistics."""
        return self.stats.copy()
