"""Binance Futures API client for REST and WebSocket operations."""

import time
import hmac
import hashlib
import logging
from typing import Dict, Optional, Any, List
from decimal import Decimal, ROUND_DOWN
from threading import Lock
from enum import Enum

import requests


logger = logging.getLogger(__name__)


class BinanceAPIError(Exception):
    """Custom exception for Binance API errors."""
    pass


class PositionSide(Enum):
    """Position side for hedge mode."""
    BOTH = "BOTH"  # One-way mode
    LONG = "LONG"  # Hedge mode long
    SHORT = "SHORT"  # Hedge mode short


class MarginType(Enum):
    """Margin type."""
    ISOLATED = "ISOLATED"
    CROSSED = "CROSSED"


class BinanceFuturesClient:
    """
    Binance Futures API client with comprehensive features.
    
    Features:
    - Time synchronization
    - Rate limiting
    - Precision handling
    - Balance checking
    - Leverage management
    - Position mode management
    """

    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://fapi.binance.com") -> None:
        """
        Initialize Binance Futures API client.
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            base_url: Base URL for Binance Futures API
                     Production: https://fapi.binance.com
                     Testnet: https://testnet.binancefuture.com
        """
        self.api_key = api_key
        self.api_secret = api_secret.encode('utf-8')
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})
        
        # Time synchronization
        self.time_offset = 0
        self._sync_time()
        
        # Rate limiting
        self.request_lock = Lock()
        self.last_request_time = 0
        self.min_request_interval = 0.05  # 50ms
        
        # Cache
        self._symbol_info_cache: Dict[str, Dict[str, Any]] = {}
        self._balance_cache: Dict[str, Decimal] = {}
        self._balance_cache_time = 0
        self._balance_cache_ttl = 5  # 5 seconds TTL

    def _sync_time(self, retry_count: int = 3) -> None:
        """
        Synchronize local time with Binance server time.
        
        Args:
            retry_count: Number of retry attempts
            
        Raises:
            Exception: If time sync fails after all retries
        """
        for attempt in range(retry_count):
            try:
                response = self.session.get(f"{self.base_url}/fapi/v1/time", timeout=5)
                response.raise_for_status()
                server_time = response.json()['serverTime']
                local_time = int(time.time() * 1000)
                self.time_offset = server_time - local_time
                logger.info(f"Time synchronized successfully. Offset: {self.time_offset}ms")
                return
            except Exception as e:
                if attempt == retry_count - 1:
                    logger.error(f"Failed to sync time after {retry_count} attempts: {e}")
                    raise Exception(f"Critical: Time synchronization failed after {retry_count} attempts. Cannot proceed.")
                logger.warning(f"Time sync attempt {attempt + 1}/{retry_count} failed: {e}. Retrying...")
                time.sleep(1)
    
    def _get_timestamp(self) -> int:
        """Get current timestamp adjusted for server time offset."""
        return int(time.time() * 1000) + self.time_offset
    
    def _sign_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Sign request parameters with HMAC SHA256."""
        query = "&".join(f"{k}={v}" for k, v in params.items())
        signature = hmac.new(
            self.api_secret,
            query.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        params['signature'] = signature
        return params

    def _request(self, method: str, endpoint: str, signed: bool = False, **kwargs) -> Dict[str, Any]:
        """Make HTTP request to Binance Futures API."""
        url = f"{self.base_url}{endpoint}"
        
        if signed:
            params = kwargs.get('params', {})
            params['timestamp'] = self._get_timestamp()
            if 'recvWindow' not in params:
                params['recvWindow'] = 5000
            params = self._sign_params(params)
            kwargs['params'] = params
        
        # Rate limiting
        with self.request_lock:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
            self.last_request_time = time.time()
        
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, timeout=10, **kwargs)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as e:
                error_msg = f"HTTP error: {e}"
                try:
                    error_data = response.json()
                    error_code = error_data.get('code')
                    error_msg = f"Binance API error [{error_code}]: {error_data.get('msg', error_data)}"
                    
                    if error_code == -1021:  # Timestamp error
                        logger.warning("Timestamp out of sync, re-syncing...")
                        self._sync_time()
                        if attempt < max_retries - 1:
                            continue
                except:
                    pass
                logger.error(error_msg)
                raise BinanceAPIError(error_msg) from e
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_delay * (2 ** attempt))
                    continue
                error_msg = f"Request error after {max_retries} attempts: {e}"
                logger.error(error_msg)
                raise BinanceAPIError(error_msg) from e

    # ==================== Account Management ====================

    def get_account_info(self) -> Dict[str, Any]:
        """Get current account information including balances and positions."""
        return self._request('GET', '/fapi/v2/account', signed=True)

    def get_balance(self, asset: str = "USDT") -> Decimal:
        """
        Get available balance for specific asset (with caching).
        
        Args:
            asset: Asset symbol (default: USDT)
            
        Returns:
            Available balance as Decimal
        """
        # Check cache
        current_time = time.time()
        if (asset in self._balance_cache and 
            current_time - self._balance_cache_time < self._balance_cache_ttl):
            return self._balance_cache[asset]
        
        # Fetch fresh data
        account_info = self.get_account_info()
        
        for asset_info in account_info.get('assets', []):
            if asset_info['asset'] == asset:
                balance = Decimal(asset_info['availableBalance'])
                self._balance_cache[asset] = balance
                self._balance_cache_time = current_time
                return balance
        
        return Decimal('0')

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current position for a symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Position info or None if no position
        """
        account_info = self.get_account_info()
        
        for position in account_info.get('positions', []):
            if position['symbol'] == symbol:
                position_amt = Decimal(position['positionAmt'])
                if position_amt != 0:
                    return position
        
        return None

    # ==================== Leverage & Margin Management ====================

    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """
        Set leverage for a symbol.
        
        Args:
            symbol: Trading pair symbol
            leverage: Leverage (1-125)
            
        Returns:
            API response
        """
        params = {
            'symbol': symbol,
            'leverage': leverage
        }
        
        logger.info(f"Setting leverage for {symbol}: {leverage}x")
        result = self._request('POST', '/fapi/v1/leverage', signed=True, params=params)
        logger.info(f"Leverage set successfully: {leverage}x")
        
        return result

    def set_margin_type(self, symbol: str, margin_type: MarginType) -> Dict[str, Any]:
        """
        Set margin type for a symbol.
        
        Args:
            symbol: Trading pair symbol
            margin_type: ISOLATED or CROSSED
            
        Returns:
            API response
        """
        params = {
            'symbol': symbol,
            'marginType': margin_type.value
        }
        
        logger.info(f"Setting margin type for {symbol}: {margin_type.value}")
        
        try:
            result = self._request('POST', '/fapi/v1/marginType', signed=True, params=params)
            logger.info(f"Margin type set successfully: {margin_type.value}")
            return result
        except BinanceAPIError as e:
            # Ignore error if margin type is already set
            if 'No need to change margin type' in str(e):
                logger.debug(f"Margin type already set to {margin_type.value}")
                return {'msg': 'Already set'}
            raise

    def set_position_mode(self, dual_side: bool) -> Dict[str, Any]:
        """
        Set position mode (hedge mode or one-way mode).
        
        Args:
            dual_side: True for hedge mode, False for one-way mode
            
        Returns:
            API response
        """
        params = {'dualSidePosition': 'true' if dual_side else 'false'}
        
        mode = "Hedge Mode" if dual_side else "One-Way Mode"
        logger.info(f"Setting position mode: {mode}")
        
        try:
            result = self._request('POST', '/fapi/v1/positionSide/dual', signed=True, params=params)
            logger.info(f"Position mode set successfully: {mode}")
            return result
        except BinanceAPIError as e:
            # Ignore error if position mode is already set
            if 'No need to change position side' in str(e):
                logger.debug(f"Position mode already set to {mode}")
                return {'msg': 'Already set'}
            raise

    # ==================== Symbol Information ====================

    def get_exchange_info(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Get exchange trading rules and symbol information."""
        params = {}
        if symbol:
            params['symbol'] = symbol
        
        return self._request('GET', '/fapi/v1/exchangeInfo', params=params)

    def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """
        Get detailed symbol information (with caching).
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Symbol info including filters
        """
        if symbol in self._symbol_info_cache:
            return self._symbol_info_cache[symbol]
        
        exchange_info = self.get_exchange_info(symbol)
        
        for symbol_info in exchange_info.get('symbols', []):
            if symbol_info['symbol'] == symbol:
                self._symbol_info_cache[symbol] = symbol_info
                return symbol_info
        
        raise BinanceAPIError(f"Symbol not found: {symbol}")

    def get_symbol_filters(self, symbol: str) -> Dict[str, Any]:
        """Get trading filters for a specific symbol."""
        symbol_info = self.get_symbol_info(symbol)
        
        filters = {}
        for f in symbol_info.get('filters', []):
            filters[f['filterType']] = f
        
        return filters

    # ==================== Precision Handling ====================

    def adjust_quantity_precision(self, symbol: str, quantity: float) -> str:
        """
        Adjust quantity to match symbol's LOT_SIZE filter.
        
        Args:
            symbol: Trading pair symbol
            quantity: Raw quantity
            
        Returns:
            Formatted quantity string
        """
        filters = self.get_symbol_filters(symbol)
        lot_size = filters.get('LOT_SIZE', {})
        
        step_size = Decimal(lot_size.get('stepSize', '0.001'))
        min_qty = Decimal(lot_size.get('minQty', '0'))
        max_qty = Decimal(lot_size.get('maxQty', '9000000'))
        
        qty_decimal = Decimal(str(quantity))
        
        if qty_decimal < min_qty:
            raise ValueError(f"Quantity {quantity} below minimum {min_qty} for {symbol}")
        if qty_decimal > max_qty:
            qty_decimal = max_qty
        
        # Adjust to step size
        precision = abs(step_size.as_tuple().exponent)
        qty_decimal = (qty_decimal / step_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_size
        
        qty_str = f"{qty_decimal:.{precision}f}".rstrip('0').rstrip('.')
        
        return qty_str

    def adjust_price_precision(self, symbol: str, price: float) -> str:
        """
        Adjust price to match symbol's PRICE_FILTER.
        
        Args:
            symbol: Trading pair symbol
            price: Raw price
            
        Returns:
            Formatted price string
        """
        filters = self.get_symbol_filters(symbol)
        price_filter = filters.get('PRICE_FILTER', {})
        
        tick_size = Decimal(price_filter.get('tickSize', '0.01'))
        min_price = Decimal(price_filter.get('minPrice', '0'))
        max_price = Decimal(price_filter.get('maxPrice', '1000000'))
        
        price_decimal = Decimal(str(price))
        
        if price_decimal < min_price:
            raise ValueError(f"Price {price} below minimum {min_price} for {symbol}")
        if price_decimal > max_price:
            price_decimal = max_price
        
        # Adjust to tick size
        precision = abs(tick_size.as_tuple().exponent)
        price_decimal = (price_decimal / tick_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick_size
        
        price_str = f"{price_decimal:.{precision}f}".rstrip('0').rstrip('.')
        
        return price_str

    def check_min_notional(self, symbol: str, quantity: float, price: float) -> bool:
        """
        Check if order meets MIN_NOTIONAL requirement.
        
        Args:
            symbol: Trading pair symbol
            quantity: Order quantity
            price: Order price
            
        Returns:
            True if meets requirement, False otherwise
        """
        filters = self.get_symbol_filters(symbol)
        min_notional_filter = filters.get('MIN_NOTIONAL', {})
        
        if not min_notional_filter:
            return True
        
        min_notional = Decimal(min_notional_filter.get('notional', '0'))
        order_notional = Decimal(str(quantity)) * Decimal(str(price))
        
        return order_notional >= min_notional

    # ==================== Order Management ====================

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        position_side: PositionSide = PositionSide.BOTH,
        reduce_only: bool = False,
        stop_price: Optional[float] = None,
        time_in_force: str = 'GTC'
    ) -> Dict[str, Any]:
        """
        Place an order on Binance Futures.
        
        Args:
            symbol: Trading pair symbol
            side: BUY or SELL
            order_type: MARKET, LIMIT, STOP, TAKE_PROFIT, etc.
            quantity: Order quantity
            price: Order price (required for LIMIT orders)
            position_side: BOTH, LONG, or SHORT
            reduce_only: True to only reduce position
            stop_price: Stop price for stop orders
            time_in_force: GTC, IOC, FOK
            
        Returns:
            Order response
        """
        # Adjust quantity precision
        adjusted_qty = self.adjust_quantity_precision(symbol, quantity)
        
        params = {
            'symbol': symbol,
            'side': side.upper(),
            'type': order_type.upper(),
            'quantity': adjusted_qty,
            'positionSide': position_side.value
        }
        
        if reduce_only:
            params['reduceOnly'] = 'true'
        
        if order_type.upper() == 'LIMIT':
            if price is None:
                raise ValueError("Price is required for LIMIT orders")
            adjusted_price = self.adjust_price_precision(symbol, price)
            params['price'] = adjusted_price
            params['timeInForce'] = time_in_force
            
            # Check MIN_NOTIONAL
            if not self.check_min_notional(symbol, quantity, price):
                filters = self.get_symbol_filters(symbol)
                min_notional = filters.get('MIN_NOTIONAL', {}).get('notional', 'N/A')
                raise ValueError(f"Order value too small. MIN_NOTIONAL: {min_notional}")
        
        if stop_price is not None:
            adjusted_stop_price = self.adjust_price_precision(symbol, stop_price)
            params['stopPrice'] = adjusted_stop_price
        
        logger.info(f"Placing {side} {order_type} order: {adjusted_qty} {symbol}" + 
                   (f" @ {params.get('price')}" if price else ""))
        
        result = self._request('POST', '/fapi/v1/order', signed=True, params=params)
        
        logger.info(f"Order placed: orderId={result.get('orderId')}, status={result.get('status')}")
        
        return result

    def place_batch_orders(self, orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Place multiple orders in a single request (up to 5 orders).
        
        Args:
            orders: List of order parameters
            
        Returns:
            List of order responses
        """
        if len(orders) > 5:
            raise ValueError("Maximum 5 orders per batch")
        
        import json
        batch_orders = []
        
        for order in orders:
            order_params = {
                'symbol': order['symbol'],
                'side': order['side'].upper(),
                'type': order['type'].upper(),
                'quantity': self.adjust_quantity_precision(order['symbol'], order['quantity']),
                'positionSide': order.get('positionSide', 'BOTH')
            }
            
            if order['type'].upper() == 'LIMIT':
                order_params['price'] = self.adjust_price_precision(order['symbol'], order['price'])
                order_params['timeInForce'] = order.get('timeInForce', 'GTC')
            
            batch_orders.append(order_params)
        
        params = {
            'batchOrders': json.dumps(batch_orders)
        }
        
        logger.info(f"Placing batch order: {len(batch_orders)} orders")
        result = self._request('POST', '/fapi/v1/batchOrders', signed=True, params=params)
        logger.info(f"Batch order placed successfully")
        
        return result

    # ==================== User Data Stream ====================

    def create_listen_key(self) -> str:
        """Create a user data stream listenKey."""
        logger.info("Creating new listen key")
        data = self._request('POST', '/fapi/v1/listenKey')
        listen_key = data['listenKey']
        logger.info(f"Listen key created: {listen_key[:8]}...")
        return listen_key

    def keepalive_listen_key(self, listen_key: str) -> None:
        """Keep the user data stream alive."""
        logger.debug(f"Keeping listen key alive: {listen_key[:8]}...")
        self._request('PUT', '/fapi/v1/listenKey')

    def close_listen_key(self, listen_key: str) -> None:
        """Close a user data stream."""
        logger.info(f"Closing listen key: {listen_key[:8]}...")
        self._request('DELETE', '/fapi/v1/listenKey')

    # ==================== Market Data ====================

    def get_ticker_price(self, symbol: str) -> Decimal:
        """Get current market price for a symbol."""
        params = {'symbol': symbol}
        result = self._request('GET', '/fapi/v1/ticker/price', params=params)
        return Decimal(result['price'])

    def get_mark_price(self, symbol: str) -> Decimal:
        """Get current mark price for a symbol."""
        params = {'symbol': symbol}
        result = self._request('GET', '/fapi/v1/premiumIndex', params=params)
        return Decimal(result['markPrice'])
