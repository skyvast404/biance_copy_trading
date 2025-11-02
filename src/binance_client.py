"""Binance API client for REST and WebSocket operations."""

import time
import hmac
import hashlib
import logging
from typing import Dict, Optional, Any
from decimal import Decimal, ROUND_DOWN
from threading import Lock

import requests


logger = logging.getLogger(__name__)


class BinanceAPIError(Exception):
    """Custom exception for Binance API errors."""
    pass


class BinanceClient:
    """
    Lightweight REST client for Binance with basic signing logic.
    
    Handles authentication, request signing, and basic API operations.
    """

    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://api.binance.com") -> None:
        """
        Initialize Binance API client.
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            base_url: Base URL for Binance API (use testnet URL for testing)
        """
        self.api_key = api_key
        self.api_secret = api_secret.encode('utf-8')
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})
        
        # Time synchronization
        self.time_offset = 0  # Offset between local and server time
        self._sync_time()
        
        # Rate limiting
        self.request_lock = Lock()
        self.last_request_time = 0
        self.min_request_interval = 0.05  # 50ms between requests
        
        # Symbol filters cache
        self._symbol_filters_cache: Dict[str, Dict[str, Any]] = {}

    def _sync_time(self) -> None:
        """
        Synchronize local time with Binance server time.
        Should be called periodically to maintain accuracy.
        """
        try:
            response = self.session.get(f"{self.base_url}/api/v3/time", timeout=5)
            response.raise_for_status()
            server_time = response.json()['serverTime']
            local_time = int(time.time() * 1000)
            self.time_offset = server_time - local_time
            logger.debug(f"Time synchronized. Offset: {self.time_offset}ms")
        except Exception as e:
            logger.warning(f"Failed to sync time: {e}. Using local time.")
            self.time_offset = 0
    
    def _get_timestamp(self) -> int:
        """
        Get current timestamp adjusted for server time offset.
        
        Returns:
            Timestamp in milliseconds
        """
        return int(time.time() * 1000) + self.time_offset
    
    def _sign_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sign request parameters with HMAC SHA256.
        
        Args:
            params: Request parameters to sign
            
        Returns:
            Parameters with signature added
        """
        query = "&".join(f"{k}={v}" for k, v in params.items())
        signature = hmac.new(
            self.api_secret,
            query.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        params['signature'] = signature
        return params

    def _request(self, method: str, endpoint: str, signed: bool = False, **kwargs) -> Dict[str, Any]:
        """
        Make HTTP request to Binance API.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint
            signed: Whether to sign the request
            **kwargs: Additional request parameters
            
        Returns:
            JSON response from API
            
        Raises:
            BinanceAPIError: If API returns an error
        """
        url = f"{self.base_url}{endpoint}"
        
        if signed:
            params = kwargs.get('params', {})
            params['timestamp'] = self._get_timestamp()
            # Add recvWindow to handle network latency (default 5000ms)
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
                    
                    # Handle specific error codes
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
                    time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                    continue
                error_msg = f"Request error after {max_retries} attempts: {e}"
                logger.error(error_msg)
                raise BinanceAPIError(error_msg) from e

    def create_listen_key(self) -> str:
        """
        Create a user data stream listenKey for the spot account.
        
        Returns:
            Listen key string
            
        Raises:
            BinanceAPIError: If API request fails
        """
        logger.info("Creating new listen key")
        data = self._request('POST', '/api/v3/userDataStream')
        listen_key = data['listenKey']
        logger.info(f"Listen key created: {listen_key[:8]}...")
        return listen_key

    def keepalive_listen_key(self, listen_key: str) -> None:
        """
        Ping the user data stream to keep it alive.
        Should be called at least once every 30 minutes.
        
        Args:
            listen_key: The listen key to keep alive
            
        Raises:
            BinanceAPIError: If API request fails
        """
        logger.debug(f"Keeping listen key alive: {listen_key[:8]}...")
        self._request('PUT', '/api/v3/userDataStream', params={'listenKey': listen_key})

    def close_listen_key(self, listen_key: str) -> None:
        """
        Close a user data stream.
        
        Args:
            listen_key: The listen key to close
            
        Raises:
            BinanceAPIError: If API request fails
        """
        logger.info(f"Closing listen key: {listen_key[:8]}...")
        self._request('DELETE', '/api/v3/userDataStream', params={'listenKey': listen_key})

    def adjust_quantity_precision(self, symbol: str, quantity: float) -> str:
        """
        Adjust quantity to match symbol's LOT_SIZE filter.
        
        Args:
            symbol: Trading pair symbol
            quantity: Raw quantity
            
        Returns:
            Formatted quantity string that complies with LOT_SIZE rules
        """
        filters = self.get_symbol_filters(symbol)
        lot_size = filters.get('LOT_SIZE', {})
        
        step_size = Decimal(lot_size.get('stepSize', '0.00000001'))
        min_qty = Decimal(lot_size.get('minQty', '0'))
        max_qty = Decimal(lot_size.get('maxQty', '9000000'))
        
        # Convert to Decimal for precise calculation
        qty_decimal = Decimal(str(quantity))
        
        # Check min/max
        if qty_decimal < min_qty:
            raise ValueError(f"Quantity {quantity} below minimum {min_qty} for {symbol}")
        if qty_decimal > max_qty:
            qty_decimal = max_qty
        
        # Adjust to step size
        precision = abs(step_size.as_tuple().exponent)
        qty_decimal = (qty_decimal / step_size).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_size
        
        # Format without trailing zeros
        qty_str = f"{qty_decimal:.{precision}f}".rstrip('0').rstrip('.')
        
        return qty_str
    
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        time_in_force: str = 'GTC'
    ) -> Dict[str, Any]:
        """
        Submit an order to Binance.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            side: Order side ('BUY' or 'SELL')
            order_type: Order type ('MARKET', 'LIMIT', etc.)
            quantity: Order quantity
            price: Order price (required for LIMIT orders)
            time_in_force: Time in force (default: 'GTC')
            
        Returns:
            Order response from API
            
        Raises:
            BinanceAPIError: If API request fails
        """
        # Adjust quantity precision according to symbol filters
        adjusted_qty = self.adjust_quantity_precision(symbol, quantity)
        
        params = {
            'symbol': symbol,
            'side': side.upper(),
            'type': order_type.upper(),
            'quantity': adjusted_qty
        }
        
        if order_type.upper() == 'LIMIT':
            if price is None:
                raise ValueError("Price is required for LIMIT orders")
            # TODO: Also adjust price precision based on PRICE_FILTER
            params['price'] = f"{price:.8f}".rstrip('0').rstrip('.')
            params['timeInForce'] = time_in_force
        
        logger.info(f"Placing {side} {order_type} order: {quantity} {symbol}" + 
                   (f" @ {price}" if price else ""))
        
        result = self._request('POST', '/api/v3/order', signed=True, params=params)
        
        logger.info(f"Order placed successfully: orderId={result.get('orderId')}, "
                   f"status={result.get('status')}")
        
        return result

    def get_exchange_info(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Get exchange trading rules and symbol information.
        
        Args:
            symbol: Optional symbol to get info for specific pair
            
        Returns:
            Exchange info from API
            
        Raises:
            BinanceAPIError: If API request fails
        """
        params = {}
        if symbol:
            params['symbol'] = symbol
        
        return self._request('GET', '/api/v3/exchangeInfo', params=params)

    def get_account_info(self) -> Dict[str, Any]:
        """
        Get current account information.
        
        Returns:
            Account info from API
            
        Raises:
            BinanceAPIError: If API request fails
        """
        return self._request('GET', '/api/v3/account', signed=True)

    def get_symbol_filters(self, symbol: str) -> Dict[str, Any]:
        """
        Get trading filters for a specific symbol (with caching).
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Dictionary of filters (LOT_SIZE, PRICE_FILTER, etc.)
            
        Raises:
            BinanceAPIError: If symbol not found
        """
        # Check cache first
        if symbol in self._symbol_filters_cache:
            return self._symbol_filters_cache[symbol]
        
        exchange_info = self.get_exchange_info(symbol)
        
        for symbol_info in exchange_info.get('symbols', []):
            if symbol_info['symbol'] == symbol:
                filters = {}
                for f in symbol_info.get('filters', []):
                    filters[f['filterType']] = f
                
                # Cache the result
                self._symbol_filters_cache[symbol] = filters
                return filters
        
        raise BinanceAPIError(f"Symbol not found: {symbol}")
