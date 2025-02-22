"""
A component which presents Yahoo Finance stock quotes.

https://github.com/iprak/yahoofinance
"""

import logging

from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.helpers.entity import Entity, async_generate_entity_id

from .const import (
    ATTR_CURRENCY_SYMBOL,
    ATTR_QUOTE_SOURCE_NAME,
    ATTR_QUOTE_TYPE,
    ATTR_SYMBOL,
    ATTR_TRENDING,
    ATTRIBUTION,
    CONF_DECIMAL_PLACES,
    CONF_SHOW_TRENDING_ICON,
    CONF_SYMBOLS,
    CONF_TARGET_CURRENCY,
    CURRENCY_CODES,
    DATA_CURRENCY_SYMBOL,
    DATA_FINANCIAL_CURRENCY,
    DATA_QUOTE_SOURCE_NAME,
    DATA_QUOTE_TYPE,
    DATA_REGULAR_MARKET_PREVIOUS_CLOSE,
    DATA_REGULAR_MARKET_PRICE,
    DATA_SHORT_NAME,
    DEFAULT_CURRENCY,
    DEFAULT_ICON,
    DOMAIN,
    HASS_DATA_CONFIG,
    HASS_DATA_COORDINATOR,
    NUMERIC_DATA_KEYS,
)

_LOGGER = logging.getLogger(__name__)
ENTITY_ID_FORMAT = DOMAIN + ".{}"


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Yahoo Finance sensor platform."""

    coordinator = hass.data[DOMAIN][HASS_DATA_COORDINATOR]
    domain_config = hass.data[DOMAIN][HASS_DATA_CONFIG]
    symbols = domain_config[CONF_SYMBOLS]

    options = {
        CONF_TARGET_CURRENCY: domain_config.get(CONF_TARGET_CURRENCY),
        CONF_DECIMAL_PLACES: domain_config[CONF_DECIMAL_PLACES],
        CONF_SHOW_TRENDING_ICON: domain_config[CONF_SHOW_TRENDING_ICON],
    }

    sensors = [
        YahooFinanceSensor(hass, coordinator, symbol, options) for symbol in symbols
    ]

    async_add_entities(sensors, update_before_add=False)
    _LOGGER.info("Platform added sensors for %s", symbols)


class YahooFinanceSensor(Entity):
    """Defines a Yahoo finance sensor."""

    _currency = DEFAULT_CURRENCY
    _icon = DEFAULT_ICON
    _market_price = None
    _short_name = None
    _target_currency = None
    _original_currency = None

    def __init__(self, hass, coordinator, symbol_definition, options) -> None:
        """Initialize the sensor."""
        symbol = symbol_definition.get("symbol")
        self._hass = hass
        self._symbol = symbol
        self._coordinator = coordinator
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, symbol, hass=hass)
        self._show_trending_icon = options[CONF_SHOW_TRENDING_ICON]
        self._decimal_places = options[CONF_DECIMAL_PLACES]
        self._previous_close = None

        # if not symbol.endswith("=X"):
        self._target_currency = symbol_definition.get(CONF_TARGET_CURRENCY)

        self._attributes = {
            ATTR_ATTRIBUTION: ATTRIBUTION,
            ATTR_CURRENCY_SYMBOL: None,
            ATTR_SYMBOL: symbol,
            ATTR_QUOTE_TYPE: None,
            ATTR_QUOTE_SOURCE_NAME: None,
        }

        # Initialize all numeric attributes to None
        for value in NUMERIC_DATA_KEYS:
            key = value[0]
            self._attributes[key] = None

        # Delay initial data population to `available` which is called from `_async_write_ha_state`
        _LOGGER.debug(
            "Created %s target_currency=%s", self.entity_id, self._target_currency
        )

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        if self._short_name is not None:
            return self._short_name

        return self._symbol

    @property
    def should_poll(self) -> bool:
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._round(self._market_price)

    @property
    def unit_of_measurement(self) -> str:
        """Return the unit of measurement of this entity, if any."""
        return self._currency

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._attributes

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend, if any."""
        return self._icon

    def _round(self, value):
        """Return formatted value based on decimal_places."""
        if value is None:
            return None

        if self._decimal_places < 0:
            return value
        if self._decimal_places == 0:
            return int(value)

        return round(value, self._decimal_places)

    def _get_target_currency_conversion(self) -> float:
        if self._target_currency and self._original_currency:
            data = self._coordinator.data
            if data is not None:
                source_symbol = (
                    f"{self._original_currency}{self._target_currency}=X".upper()
                )
                _LOGGER.debug(f"Conversion symbol = {source_symbol}")
                symbol_data = data.get(source_symbol)

                if symbol_data is not None:
                    return symbol_data[DATA_REGULAR_MARKET_PRICE]
                else:
                    self._coordinator.add_symbol(source_symbol)

        return None

    @staticmethod
    def safe_convert(value, conversion):
        """Return the converted value. The original value is returned if there is no conversion."""
        if value is None:
            return None
        if conversion is None:
            return value
        return value * conversion

    def _get_original_currency(self, symbol_data):
        # Prefer currency over financialCurrency, for foreign symbols financialCurrency
        # can represent the remote currency. But financialCurrency can also be None.
        financial_currency = symbol_data[DATA_FINANCIAL_CURRENCY]
        currency = symbol_data[DATA_CURRENCY_SYMBOL]

        _LOGGER.debug(
            "Updated %s (currency=%s, financialCurrency=%s)",
            self._symbol,
            ("None" if currency is None else currency),
            ("None" if financial_currency is None else financial_currency),
        )

        currency = currency or financial_currency or DEFAULT_CURRENCY
        return currency

    def _update_data(self) -> None:
        """Update local fields."""

        data = self._coordinator.data
        if data is None:
            _LOGGER.debug("Coordinator data is None")
            return

        symbol_data = data.get(self._symbol)
        if symbol_data is None:
            _LOGGER.debug("Symbol data is None")
            return

        self._original_currency = self._get_original_currency(symbol_data)
        conversion = self._get_target_currency_conversion()
        _LOGGER.debug(f"Currency conversion = {conversion}")

        self._short_name = symbol_data[DATA_SHORT_NAME]
        self._market_price = self.safe_convert(
            symbol_data[DATA_REGULAR_MARKET_PRICE], conversion
        )
        self._previous_close = self.safe_convert(
            symbol_data[DATA_REGULAR_MARKET_PREVIOUS_CLOSE], conversion
        )

        for value in NUMERIC_DATA_KEYS:
            key = value[0]
            attr_value = symbol_data[key]

            # Convert if currency value
            if value[1]:
                attr_value = self.safe_convert(attr_value, conversion)

            self._attributes[key] = self._round(attr_value)

        # Add some other string attributes
        self._attributes[ATTR_QUOTE_TYPE] = symbol_data[DATA_QUOTE_TYPE]
        self._attributes[ATTR_QUOTE_SOURCE_NAME] = symbol_data[DATA_QUOTE_SOURCE_NAME]

        # Use target_currency if we have conversion data, otherwise keep using the currency from data.
        if conversion is not None:
            currency = self._target_currency or self._original_currency
        else:
            currency = self._original_currency

        self._currency = currency.upper()
        lower_currency = self._currency.lower()

        trending_state = self._calc_trending_state()

        # Fall back to currency based icon if there is no trending state
        if trending_state is not None:
            self._attributes[ATTR_TRENDING] = trending_state

            if self._show_trending_icon:
                self._icon = f"mdi:trending-{trending_state}"
            else:
                self._icon = f"mdi:currency-{lower_currency}"
        else:
            self._icon = f"mdi:currency-{lower_currency}"

        # If this one of the known currencies, then include the correct currency symbol.
        # Don't show $ as the CurrencySymbol even if we can't get one.
        self._attributes[ATTR_CURRENCY_SYMBOL] = CURRENCY_CODES.get(lower_currency)

    def _calc_trending_state(self):
        """Return the trending state for the symbol."""
        if self._market_price is None or self._previous_close is None:
            return None

        if self._market_price > self._previous_close:
            return "up"
        if self._market_price < self._previous_close:
            return "down"

        return "neutral"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        self._update_data()
        return self._coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self._coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        self._coordinator.async_remove_listener(self.async_write_ha_state)

    async def async_update(self) -> None:
        """Update symbol data."""
        await self._coordinator.async_request_refresh()
