"""The time-weighted average constants."""
from homeassistant.const import Platform

DOMAIN = "tw_average"
PLATFORMS = [Platform.SENSOR]

CONF_PRECISION = "precision"
CONF_EXTREMAS = "extremas"
CONF_TOTAL_METHOD = "total_method"

DEFAULT_PRECISION = 1

ATTR_MIN_VALUE = "min_value"
ATTR_MIN_ENTITY_ID = "min_entity_id"
ATTR_MAX_VALUE = "max_value"
ATTR_MAX_ENTITY_ID = "max_entity_id"

METHOD_TIME_WEIGHTED = "time-weighted"
METHOD_LINEAR = "linear"
AVERAGE_METHODS = [METHOD_TIME_WEIGHTED, METHOD_LINEAR]

TOTAL_METHOD_SUM = "sum"
TOTAL_METHOD_AVERAGE = "average"
TOTAL_METHODS = [TOTAL_METHOD_SUM, TOTAL_METHOD_AVERAGE]
