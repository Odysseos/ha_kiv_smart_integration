# SPDX-License-Identifier: GPL-3.0-only
"""Constants for Vakio KIV Local."""
DOMAIN = "vakio_kiv_local"
PLATFORMS = ["cover", "select", "sensor"]
CONF_PREFIX = "topic_prefix"
CONF_WINDOW = "boot_report_window"
OPTIONS = ["Авто", "Нет", "Малое", "Среднее", "Большое", "Полное"]
LEVELS = {"Малое": 1, "Среднее": 2, "Большое": 3, "Полное": 4}
CONF_OVERVIEW_CLIMATE = "overview_climate"
ATTR_OVERVIEW_CLIMATE = "vakio_kiv_local_overview_climate"
