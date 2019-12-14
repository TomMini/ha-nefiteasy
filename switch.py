"""
Support for Bosch home thermostats.
For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/xxxxxx/
"""

import asyncio
import logging
from datetime import datetime, timedelta, date

from homeassistant.components.switch import SwitchDevice
from homeassistant.const import STATE_OFF, STATE_ON

from .const import (DOMAIN, SWITCH_TYPES, DATE_FORMAT, 
    CONF_SWITCHES, CONF_HOLIDAY_TEMP, CONF_HOLIDAY_DURATION)
from .nefit_device import NefitDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    client = hass.data[DOMAIN]["client"]

    devices = []
    config = hass.data[DOMAIN]["config"]
    for key in config[CONF_SWITCHES]:
        dev = SWITCH_TYPES[key]
        if key == 'hot_water':
            devices.append(NefitHotWater(client, key, dev))
        elif key == 'holiday_mode':
            temp = config[CONF_HOLIDAY_TEMP]
            duration = config[CONF_HOLIDAY_DURATION]
            devices.append(NefitHolidayMode(client, key, dev, temp, duration))
        elif key == 'home_entrance_detection':
            await setup_home_entrance_detection(devices, client, key, dev)
        else:
            devices.append(NefitSwitch(client, key, dev))

    async_add_entities(devices, True)

    _LOGGER.debug("switch: async_setup_platform done")


async def setup_home_entrance_detection(devices, client, basekey, basedev):
    for i in range(0, 10):
        userprofile_id = 'userprofile{}'.format(i)
        endpoint = '/ecus/rrc/homeentrancedetection/{}/'.format(userprofile_id)
        is_active = await client.get_value(userprofile_id, endpoint + 'active')
        _LOGGER.debug("hed switch: is_active: " + str(is_active))
        if is_active == 'on':
            name = await client.get_value(userprofile_id, endpoint + 'name')
            dev = {}
            dev['name'] = basedev['name'].format(name)
            dev['url'] = endpoint + 'detected'
            dev['icon'] = basedev['icon']
            devices.append(NefitSwitch(client, '{}_{}'.format(basekey, userprofile_id), dev))


class NefitSwitch(NefitDevice, SwitchDevice):
    """Representation of a NefitSwitch device."""

    @property
    def is_on(self):
        """Get whether the switch is in on state."""
        return self._client.data[self._key] == 'on'

    @property
    def assumed_state(self) -> bool:
        """Return true if we do optimistic updates."""
        return False

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the entity on."""
        await self.async_change_state('on')

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the entity off."""
        await self.async_change_state('off')

    async def async_change_state(self, new_state, **kwargs):
        self._client.nefit.put_value(self.get_endpoint(), new_state)
        await asyncio.wait_for(self._client.nefit.xmppclient.message_event.wait(), timeout=30)
        self._client.data[self._key] = new_state

        _LOGGER.debug("Switch Nefit %s %s, endpoint=%s.", self._key, new_state, self.get_endpoint())

class NefitHotWater(NefitSwitch):

    def __init__(self, client, key, device):
        """Initialize the switch."""
        super().__init__(client, key, device)

        client.keys['/dhwCircuits/dhwA/dhwOperationClockMode'] = self._key
        client.keys['/dhwCircuits/dhwA/dhwOperationManualMode'] = self._key
        
    def get_endpoint(self):
        endpoint = 'dhwOperationClockMode' if self._client.data.get('user_mode') == 'clock' else 'dhwOperationManualMode'
        return '/dhwCircuits/dhwA/' + endpoint


class NefitHolidayMode(NefitSwitch):

    def __init__(self, client, key, device, temp, duration):
        """Initialize the switch."""
        super().__init__(client, key, device)
        self._temp = temp
        self._duration = duration

    async def async_turn_on(self, **kwargs) -> None:      
        """Turn the entity on."""

        if self._client.data.get('user_mode') == 'manual':
            self._client.nefit.set_usermode('clock')
            await asyncio.wait_for(self._client.nefit.xmppclient.message_event.wait(), timeout=30)
            self._client.data['user_mode'] = 'clock'

        await super().async_turn_on()

        start = date.now()
        end = start + timedelta(days=self._duration)
        self._client.nefit.put_value('/heatingCircuits/hc1/holidayMode/temperature', self._temp)
        self._client.nefit.put_value('/heatingCircuits/hc1/holidayMode/start', start.strftime(DATE_FORMAT))
        self._client.nefit.put_value('/heatingCircuits/hc1/holidayMode/end', end.strftime(DATE_FORMAT))