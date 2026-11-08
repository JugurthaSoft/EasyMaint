"""Formats français d'EasyMaint : dates JJ/MM/AAAA, séparateur décimal virgule."""
DATE_FORMAT = "d/m/Y"
DATETIME_FORMAT = "d/m/Y H:i"
SHORT_DATE_FORMAT = "d/m/Y"
SHORT_DATETIME_FORMAT = "d/m/Y H:i"
TIME_FORMAT = "H:i"
DATE_INPUT_FORMATS = ["%d/%m/%Y", "%Y-%m-%d"]
DATETIME_INPUT_FORMATS = ["%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
DECIMAL_SEPARATOR = ","
THOUSAND_SEPARATOR = " "
NUMBER_GROUPING = 3
FIRST_DAY_OF_WEEK = 1
