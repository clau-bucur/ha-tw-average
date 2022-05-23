"""Time-weighted average sensor."""
from datetime import timedelta
import logging
from threading import Lock

import voluptuous as vol

from homeassistant.components.group import expand_entity_ids
from homeassistant.components.sensor import (
    CONF_STATE_CLASS,
    DEVICE_CLASSES_SCHEMA,
    DOMAIN as SENSOR_DOMAIN,
    ENTITY_ID_FORMAT,
    STATE_CLASSES_SCHEMA,
    PLATFORM_SCHEMA,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_DEVICE_CLASS,
    CONF_ENTITIES,
    CONF_FRIENDLY_NAME,
    CONF_ICON,
    CONF_METHOD,
    CONF_SCAN_INTERVAL,
    CONF_SENSORS,
    CONF_UNIQUE_ID,
    CONF_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util.dt import utcnow

from .const import (
    ATTR_MAX_ENTITY_ID,
    ATTR_MIN_ENTITY_ID,
    ATTR_MAX_VALUE,
    ATTR_MIN_VALUE,
    CONF_EXTREMAS,
    CONF_PRECISION,
    CONF_TOTAL_METHOD,
    DEFAULT_PRECISION,
    DOMAIN,
    AVERAGE_METHODS,
    METHOD_LINEAR,
    METHOD_TIME_WEIGHTED,
    PLATFORMS,
    TOTAL_METHODS,
    TOTAL_METHOD_AVERAGE,
    TOTAL_METHOD_SUM,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

SENSOR_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_FRIENDLY_NAME): cv.string,
        vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
        vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASSES_SCHEMA,
        vol.Optional(CONF_STATE_CLASS): STATE_CLASSES_SCHEMA,
        vol.Optional(CONF_ICON): cv.string,
        vol.Optional(CONF_PRECISION): cv.positive_int,
        vol.Optional(CONF_EXTREMAS): cv.boolean,
        vol.Optional(CONF_METHOD, default=METHOD_TIME_WEIGHTED): vol.In(
            AVERAGE_METHODS
        ),
        vol.Optional(CONF_TOTAL_METHOD, default=TOTAL_METHOD_SUM): vol.In(
            TOTAL_METHODS
        ),
        vol.Required(CONF_ENTITIES): cv.entity_ids,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
        vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASSES_SCHEMA,
        vol.Optional(CONF_STATE_CLASS, default=SensorStateClass.MEASUREMENT): STATE_CLASSES_SCHEMA,
        vol.Optional(CONF_ICON): cv.string,
        vol.Optional(CONF_PRECISION, default=DEFAULT_PRECISION): cv.positive_int,
        vol.Optional(CONF_EXTREMAS, default=False): cv.boolean,
        vol.Optional(CONF_METHOD, default=METHOD_TIME_WEIGHTED): vol.In(
            AVERAGE_METHODS
        ),
        vol.Optional(CONF_TOTAL_METHOD, default=TOTAL_METHOD_SUM): vol.In(
            TOTAL_METHODS
        ),
        vol.Required(CONF_SENSORS): cv.schema_with_slug_keys(SENSOR_SCHEMA)
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType = None,
) -> None:
    """Set up the time-weighted average sensors."""

    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    platform_scan_interval = config.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL)
    platform_unit_of_measurement = config.get(CONF_UNIT_OF_MEASUREMENT)
    platform_icon = config.get(CONF_ICON)
    platform_precision = config.get(CONF_PRECISION)
    platform_device_class = config.get(CONF_DEVICE_CLASS)
    platform_state_class = config.get(CONF_STATE_CLASS)
    platform_extremas = config.get(CONF_EXTREMAS)
    platform_method = config.get(CONF_METHOD)
    platform_total_method = config.get(CONF_TOTAL_METHOD)
    devices = config.get(CONF_SENSORS, {})
    sensors = []

    for object_id, device_config in devices.items():
        _LOGGER.info("Setting up %s with scan_interval %s", object_id, platform_scan_interval)
        sensors.append(
            TwAverageSensor(
                hass,
                platform_scan_interval,
                object_id,
                device_config.get(CONF_UNIQUE_ID),
                device_config.get(CONF_FRIENDLY_NAME, object_id),
                device_config.get(CONF_UNIT_OF_MEASUREMENT, platform_unit_of_measurement),
                device_config.get(CONF_ICON, platform_icon),
                device_config.get(CONF_ENTITIES),
                device_config.get(CONF_PRECISION, platform_precision),
                device_config.get(CONF_DEVICE_CLASS, platform_device_class),
                device_config.get(CONF_STATE_CLASS, platform_state_class),
                device_config.get(CONF_EXTREMAS, platform_extremas),
                device_config.get(CONF_METHOD, platform_method),
                device_config.get(CONF_TOTAL_METHOD, platform_total_method),
            )
        )

    if not sensors:
        _LOGGER.error("No sensors added")
        return

    async_add_entities(sensors)


class TwAverageSensor(SensorEntity, RestoreEntity):
    """Implementation of a time-weighted average sensor."""

    def __init__(
        self,
        hass,
        scan_interval,
        object_id,
        unique_id,
        friendly_name,
        unit_of_measurement,
        icon,
        entity_ids: list[str],
        precision,
        device_class,
        state_class,
        extremas,
        method,
        total_method,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self.scan_interval = scan_interval

        self.entity_id = ENTITY_ID_FORMAT.format(object_id)
        self._unique_id = unique_id
        self._attr_name = friendly_name
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_state_class = state_class

        self._entity_ids = expand_entity_ids(hass, entity_ids)
        self._precision = precision
        self._extremas = extremas
        self._method = method
        self._total_method = total_method

        self._attr_native_value = None
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_extra_state_attributes = {ATTR_ENTITY_ID: self._entity_ids}
        self._attr_should_poll = True

        self.lock = Lock()
        self.states = {
            e: [] for e in self._entity_ids
        }  # dict of list of tuples with (timestamp_start, state)
        self.min_value = None
        self.max_value = None
        self.min_entity_id = None
        self.max_entity_id = None

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state is not None:
            try:
                self._attr_native_value = float(state.state)
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Could not restore last state for %s: %s", self.entity_id, err)

        # Add listener
        async_track_state_change(
            self.hass, self._entity_ids, self._async_sensor_changed
        )

    async def _async_sensor_changed(self, entity_id, old_state, new_state):
        """Handle sensor changes."""
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        _LOGGER.debug("%s - state update %s: %s", self.entity_id, entity_id, new_state.state)

        try:
            value = float(new_state.state)

            with self.lock:
                self.states[entity_id].append((new_state.last_updated, value))

                if self._extremas:
                    if self.min_value is None:
                        self.min_value = self.max_value = value
                        self.min_entity_id = self.max_entity_id = entity_id
                    else:
                        if value < self.min_value:
                            self.min_value = value
                            self.min_entity_id = entity_id
                        elif value > self.max_value:
                            self.max_value = value
                            self.max_entity_id = entity_id
        except (ValueError, TypeError) as err:
            _LOGGER.warning("While adding state value for %s: %s", entity_id, err)

    def update(self):
        """Update the sensor state if needed."""
        _LOGGER.info( "%s - calculating average for the past %d states", self.entity_id, sum(len(x) for x in self.states.values()))

        now = utcnow()
        total = float(0)
        state_changed = False

        with self.lock:
            for entity_id, states in self.states.items():
                if len(states) > 0:
                    state_changed = True
                    if self._method == METHOD_LINEAR:
                        total += self.calculate_linear(entity_id, states)
                    else:
                        total += self.calculate_tw(now, entity_id, states)

        if state_changed:
            _LOGGER.debug("%s - average: %f", self.entity_id, total)
            if self._total_method == TOTAL_METHOD_AVERAGE:
                self.update_state(total / len(self.states))
            else:
                self.update_state(total)

        # reset min/max
        self.min_value = self.max_value = self.min_entity_id = self.max_entity_id = None

    def calculate_tw(self, now, entity_id, states) -> float:
        """Calculate time-weighted average."""
        result = float(0)

        last_value = states[-1][1]
        states_len = len(states) - 1

        for index, (start, value) in enumerate(states):
            # if last element in the list, end time is the end of the scan interval
            end = states[index + 1][0] if index < states_len else now
            result += value * (end - start).total_seconds()

            _LOGGER.debug("%s - TW data for entity %s: start %s, end %s, state %s", self.entity_id, entity_id, start, end, value)

        result = result / self.scan_interval.total_seconds()
        _LOGGER.debug("%s - TW average for entity %s: %f", self.entity_id, entity_id, result)

        # add last value as first value point in our graph
        self.states[entity_id].clear()
        self.states[entity_id].append((now, last_value))

        return result

    def calculate_linear(self, entity_id, states) -> float:
        """Calculate linear average."""
        values = [x[1] for x in states]
        result = sum(values) / len(values)

        self.states[entity_id].clear()

        _LOGGER.debug("%s - linear average for entity %s: %f", self.entity_id, entity_id, total)

        return result

    def update_state(self, new_value):
        """Update state of our sensor."""
        if self._precision == 0:
            average = int(new_value)
        else:
            average = round(new_value, self._precision)

        if self._attr_native_value != average:
            _LOGGER.debug("%s - update state: %f", self.entity_id, average)
            self._attr_native_value = average
            if self._extremas:
                self._attr_extra_state_attributes.update(
                    {
                        ATTR_MIN_VALUE: str(self.min_value),
                        ATTR_MIN_ENTITY_ID: self.min_entity_id,
                        ATTR_MAX_VALUE: str(self.max_value),
                        ATTR_MAX_ENTITY_ID: self.max_entity_id,
                    }
                )
            self.async_write_ha_state()

    @property
    def unique_id(self):
        """Return the unique ID."""
        return self._unique_id
