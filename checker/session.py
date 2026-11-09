"""Appium session + one full check (the app caches the date sheet within a
session, so only a fresh session shows fresh slot data).

One check: kill app -> reopen -> PIN -> navigate -> номер заявки -> SMS code
-> Шаг 3 -> read the date sheet. Scheduling lives in checker/cycle.py.
"""

import time

from appium import webdriver
from appium.options.android import UiAutomator2Options

from checker import config, flow

APP = config.APP_PACKAGE


def make_driver() -> webdriver.Remote:
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.automation_name = "UiAutomator2"
    options.set_capability("appium:autoLaunch", False)  # attach, don't launch
    options.no_reset = True
    options.new_command_timeout = 0
    return webdriver.Remote(config.APPIUM_SERVER, options=options)


def restart_app(driver) -> None:
    driver.terminate_app(APP)
    time.sleep(1)
    driver.activate_app(APP)
    time.sleep(3)
    flow.ensure_home(driver)


def run_one_check(driver, sms_mode: str = config.SMS_MODE) -> tuple[bool, str, object]:
    """Fresh session end-to-end: restart app, walk the flow, read the sheet."""
    restart_app(driver)
    flow.navigate_to_date_picker(driver, sms_mode=sms_mode)
    return flow.check_slots(driver)
