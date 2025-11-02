"""Copy trading engine that monitors master account and replicates trades to followers."""

import json
import time
import logging
from threading import Thread, Event, Lock
from typing import Dict, List, Optional, Callable, Set
from datetime import datetime, timedelta
from collections import deque

import websocket

from .binance_client import BinanceClient, BinanceAPIError
from .config_loader import Config, FollowerConfig


logger = logging.getLogger(__name__)


class CopyTradeEngine:
    """
    Engine that listens to master account trades and replicates them to follower accounts.
    
    Features:
    - WebSocket connection with auto-reconnect
    - Configurable order types for followers
    - Risk management and filtering
    - Detailed logging and error handling
    """

    def __init__(self, config: Config) -> None:
        """
        Initialize copy trade engine.
        
        Args:
            config: Configuration object with all settings
        """
        self.config = config
        
        # Initialize master account client
        self.master_client = BinanceClient(
            api_key=config.master.api_key,
            api_secret=config.master.api_secret,
            base_url=config.base_url
        )
        
        # Initialize follower clients
        self.follower_clients: Dict[str, BinanceClient] = {}
        for follower in config.followers:
            if follower.enabled:
                self.follower_clients[follower.name] = BinanceClient(
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
        
        # Order deduplication (track recent order IDs to prevent duplicates)
        self.processed_orders: deque = deque(maxlen=1000)  # Keep last 1000 order IDs
        self.order_lock = Lock()
        
        # Statistics
        self.stats = {
            'total_trades': 0,
            'successful_copies': 0,
            'failed_copies': 0,
            'duplicate_filtered': 0,
            'start_time': None
        }
        
        logger.info(f"Copy trade engine initialized with {len(self.follower_clients)} active followers")

    def start(self) -> None:
        """Start the copy trading engine."""
        if self.is_running:
            logger.warning("Engine is already running")
            return
        
        self.is_running = True
        self.stop_event.clear()
        self.stats['start_time'] = datetime.now()
        
        logger.info("Starting copy trade engine...")
        
        try:
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

    def stop(self) -> None:
        """Stop the copy trading engine."""
        if not self.is_running:
            logger.warning("Engine is not running")
            return
        
        logger.info("Stopping copy trade engine...")
        
        self.is_running = False
        self.stop_event.set()
        
        # Close WebSocket
        if self.ws:
            self.ws.close()
        
        # Close listen key
        if self.listen_key:
            try:
                self.master_client.close_listen_key(self.listen_key)
            except Exception as e:
                logger.error(f"Failed to close listen key: {e}")
        
        # Print statistics
        self._print_statistics()
        
        logger.info("Copy trade engine stopped")

    def _connect_websocket(self) -> None:
        """Connect to Binance user data stream WebSocket."""
        ws_url = f"wss://stream.binance.com:9443/ws/{self.listen_key}"
        
        # Use testnet WebSocket URL if using testnet
        if 'testnet' in self.config.base_url:
            ws_url = f"wss://testnet.binance.vision/ws/{self.listen_key}"
        
        logger.info(f"Connecting to WebSocket: {ws_url[:50]}...")
        
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
            on_ping=self._on_ping,
            on_pong=self._on_pong
        )
        
        # Run WebSocket in separate thread
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
        logger.info("✓ Connected to master account user data stream")
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
        
        # Attempt reconnection if enabled and engine is still running
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
            # Refresh listen key
            self.listen_key = self.master_client.create_listen_key()
            
            # Reconnect WebSocket
            self._connect_websocket()
            
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            self._attempt_reconnect()

    def _on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """
        Handle incoming WebSocket messages.
        
        When an executionReport indicating a fill is received,
        replicate the order to follower accounts.
        """
        try:
            data = json.loads(message)
            event_type = data.get('e')
            
            if event_type == 'executionReport':
                self._handle_execution_report(data)
            elif event_type == 'outboundAccountPosition':
                logger.debug("Received account position update")
            else:
                logger.debug(f"Received event: {event_type}")
                
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    def _handle_execution_report(self, data: Dict) -> None:
        """
        Handle execution report from master account.
        
        Args:
            data: Execution report data from WebSocket
        """
        status = data.get('X')  # Order status
        exec_type = data.get('x')  # Execution type
        order_id = data.get('i')  # Order ID
        trade_id = data.get('t')  # Trade ID
        
        # Only process trades (both FILLED and PARTIALLY_FILLED)
        if exec_type != 'TRADE':
            return
        
        # Deduplication: Check if we've already processed this trade
        trade_key = f"{order_id}_{trade_id}"
        with self.order_lock:
            if trade_key in self.processed_orders:
                logger.debug(f"Duplicate trade detected: {trade_key}, skipping")
                self.stats['duplicate_filtered'] += 1
                return
            self.processed_orders.append(trade_key)
        
        symbol = data['s']
        side = data['S']
        order_type = data['o']
        
        # Use last executed quantity (not total order quantity)
        # 'l' is the quantity of this specific fill
        last_exec_qty = float(data['l'])
        last_exec_price = float(data['L']) if data.get('L') else None
        
        # Cumulative filled quantity (for logging)
        cumulative_qty = float(data['z'])
        total_qty = float(data['q'])
        
        # Check if symbol is allowed
        if not self._is_symbol_allowed(symbol):
            logger.info(f"Symbol {symbol} is filtered out, skipping")
            return
        
        # Log with fill status
        fill_status = "FILLED" if status == 'FILLED' else f"PARTIAL ({cumulative_qty}/{total_qty})"
        logger.info(f"📊 Master {fill_status}: {side} {last_exec_qty} {symbol} @ {last_exec_price}")
        
        self.stats['total_trades'] += 1
        
        # Replicate to followers
        self._replicate_to_followers(symbol, side, last_exec_qty, last_exec_price)

    def _is_symbol_allowed(self, symbol: str) -> bool:
        """
        Check if symbol is allowed for copy trading.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            True if symbol is allowed, False otherwise
        """
        # Check excluded symbols
        if symbol in self.config.trading.excluded_symbols:
            return False
        
        # Check allowed symbols (empty list = all allowed)
        if self.config.trading.allowed_symbols:
            return symbol in self.config.trading.allowed_symbols
        
        return True

    def _replicate_to_followers(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float]
    ) -> None:
        """
        Replicate trade to all follower accounts.
        
        Args:
            symbol: Trading pair symbol
            side: Order side (BUY/SELL)
            quantity: Order quantity
            price: Execution price (for reference)
        """
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
                quantity=follower_qty
            )

    def _place_follower_order(
        self,
        follower_name: str,
        symbol: str,
        side: str,
        quantity: float
    ) -> None:
        """
        Place order for a specific follower account.
        
        Args:
            follower_name: Name of the follower account
            symbol: Trading pair symbol
            side: Order side (BUY/SELL)
            quantity: Order quantity
        """
        client = self.follower_clients.get(follower_name)
        if not client:
            logger.error(f"Follower client not found: {follower_name}")
            return
        
        order_type = self.config.trading.follower_order_type
        
        try:
            result = client.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity
            )
            
            # Log detailed order info
            order_id = result.get('orderId')
            executed_qty = result.get('executedQty', 0)
            status = result.get('status')
            
            logger.info(f"✓ Follower '{follower_name}': {side} {executed_qty}/{quantity} {symbol} - "
                       f"orderId={order_id}, status={status}")
            
            self.stats['successful_copies'] += 1
            
        except ValueError as e:
            # Quantity precision errors
            logger.error(f"✗ Follower '{follower_name}': Invalid quantity - {e}")
            self.stats['failed_copies'] += 1
        except BinanceAPIError as e:
            # API errors (insufficient balance, etc.)
            error_str = str(e)
            if 'insufficient balance' in error_str.lower():
                logger.error(f"✗ Follower '{follower_name}': Insufficient balance for {quantity} {symbol}")
            elif 'min notional' in error_str.lower():
                logger.error(f"✗ Follower '{follower_name}': Order value too small (MIN_NOTIONAL)")
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
            logger.info("COPY TRADING STATISTICS")
            logger.info("=" * 60)
            logger.info(f"Runtime: {runtime}")
            logger.info(f"Total master trades: {self.stats['total_trades']}")
            logger.info(f"Successful copies: {self.stats['successful_copies']}")
            logger.info(f"Failed copies: {self.stats['failed_copies']}")
            logger.info(f"Duplicates filtered: {self.stats['duplicate_filtered']}")
            
            total_attempts = self.stats['successful_copies'] + self.stats['failed_copies']
            if total_attempts > 0:
                success_rate = (self.stats['successful_copies'] / total_attempts) * 100
                logger.info(f"Success rate: {success_rate:.2f}%")
            
            logger.info("=" * 60)

    def get_statistics(self) -> Dict:
        """
        Get current trading statistics.
        
        Returns:
            Dictionary with statistics
        """
        return self.stats.copy()
