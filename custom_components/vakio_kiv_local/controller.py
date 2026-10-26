# SPDX-License-Identifier: GPL-3.0-only
"""One state machine and one persistent store per config entry."""
import asyncio
from collections.abc import Callable
import json
import logging

from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt

from .const import CONF_PREFIX, CONF_WINDOW, DOMAIN, LEVELS
from .state import ValveState, capabilities, measurement

_LOGGER = logging.getLogger(__name__)


class ValveController:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.prefix = entry.data[CONF_PREFIX]
        self.window = entry.options.get(CONF_WINDOW, entry.data.get(CONF_WINDOW, 3))
        self.state = ValveState.seasonal(dt.now().month)
        self.temperature = None
        self.humidity = None
        self.connected = False
        self.source = "saved_target"
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.lock = asyncio.Lock()
        self.listeners: set[Callable] = set()
        self.unsubscribers = []
        self.tasks = set()
        self.last_event = 0.0
        self.closed = False

    @callback
    def notify(self):
        for listener in tuple(self.listeners):
            listener()

    @callback
    def add_listener(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    @callback
    def spawn(self, kind, payload):
        if self.closed:
            return
        # Capture receipt time before scheduling; reports may wait while commands proceed.
        received = self.hass.loop.time()
        task = self.hass.async_create_background_task(
            self._handle_safely(kind, payload, received), f"{DOMAIN} {kind}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _handle_safely(self, kind, payload, received):
        try:
            await self.handle(kind, payload, received)
        except Exception:
            _LOGGER.exception("Failed to process %s for config entry %s", kind, self.entry.entry_id)

    async def start(self):
        saved = await self.store.async_load()
        self.state = ValveState.load(saved) or ValveState.seasonal(dt.now().month)
        self.last_event = self.hass.loop.time()
        self.connected = mqtt.is_connected(self.hass)
        topics = {
            f"server/{self.prefix}/kivsmart/mode": "command",
            f"device/{self.prefix}/kivsmart/mode": "report",
            f"device/{self.prefix}/kivsmart/system": "system",
            f"{self.prefix}/workmode": "workmode",
            f"{self.prefix}/temp": "temperature",
            f"{self.prefix}/hud": "humidity",
        }
        try:
            for topic, kind in topics.items():
                @callback
                def receive(msg, kind=kind):
                    self.spawn(kind, msg.payload)
                self.unsubscribers.append(await mqtt.async_subscribe(self.hass, topic, receive, qos=1))
            self.unsubscribers.append(mqtt.async_subscribe_connection_status(self.hass, self.connection_changed))
        except Exception:
            await self.stop()
            raise

    @callback
    def connection_changed(self, connected):
        self.connected = connected
        self.notify()
        if connected:
            self.spawn("restore", "")

    async def stop(self):
        self.closed = True
        for unsubscribe in self.unsubscribers:
            unsubscribe()
        self.unsubscribers.clear()
        for task in tuple(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        self.listeners.clear()

    async def remove(self):
        await self.store.async_remove()

    async def _save(self, target=None, source=None):
        # Commit only after durable save; failed storage must not advance UI state.
        target = self.state if target is None else target
        await self.store.async_save(target.dump())
        self.state = target
        if source is not None:
            self.source = source
        self.notify()

    async def _transmit(self):
        if not self.connected:
            return
        command = {"on_off": self.state.power}
        if self.state.mode == "manual":
            await mqtt.async_publish(self.hass, f"{self.prefix}/workmode", "manual", qos=1, retain=False)
            if self.state.power == "on":
                command["gate"] = self.state.gate
        await mqtt.async_publish(self.hass, f"server/{self.prefix}/kivsmart/mode",
                                 json.dumps({"capabilities": command}), qos=1, retain=False)
        if self.state.mode == "super_auto":
            await mqtt.async_publish(self.hass, f"{self.prefix}/workmode", "super_auto", qos=1, retain=False)

    async def set_option(self, option):
        if option == "Авто":
            caps = {"mode": "super_auto", "on_off": "on"}
        elif option == "Нет":
            caps = {"mode": "manual", "on_off": "off"}
        elif option in LEVELS:
            caps = {"mode": "manual", "on_off": "on", "gate": LEVELS[option]}
        else:
            raise ValueError("Unknown valve option")
        await self.command(caps)

    async def set_position(self, position):
        if not 0 <= position <= 100:
            raise ValueError("Position must be between 0 and 100")
        if position == 0:
            await self.set_option("Нет")
            return
        await self.command({"mode": "manual", "on_off": "on", "gate": max(1, min(4, int((position + 12.5) / 25)))})

    async def command(self, caps):
        async with self.lock:
            self.last_event = self.hass.loop.time()
            await self._save(self.state.merge(caps), "command_target")
            await self._transmit()

    async def restore(self):
        await self.handle("restore", "", self.hass.loop.time())

    async def handle(self, kind, payload, received=None):
        received = self.hass.loop.time() if received is None else received
        if kind in ("temperature", "humidity"):
            value = measurement(payload, kind == "humidity")
            if value is not None:
                setattr(self, kind, value)
                self.notify()
            return
        if kind == "system":
            try:
                msg = json.loads(payload)
            except (ValueError, TypeError):
                return
            if not isinstance(msg, dict) or msg.get("type") != "auth":
                return
            kind = "restore"
        if kind == "restore":
            async with self.lock:
                self.last_event = max(received, self.last_event)
                await self._save()
                await self._transmit()
            return
        caps = {"mode": payload} if kind == "workmode" else capabilities(payload)
        valid = (caps.get("mode") in ("manual", "super_auto")
                 or caps.get("on_off") in ("on", "off")
                 or (type(caps.get("gate")) is int and caps["gate"] in range(1, 5)))
        if kind not in ("report", "workmode", "command") or not valid:
            return
        if kind in ("report", "workmode"):
            await asyncio.sleep(self.window)
        async with self.lock:
            if self.closed or received < self.last_event:
                return
            updated = self.state.merge(caps)
            self.last_event = received
            if updated != self.state:
                source = "device_report" if kind == "report" else "external_command"
                await self._save(updated, source)
            # Own outgoing JSON deliberately omits mode; its echo must never retransmit.
            if kind == "command" and caps.get("mode") in ("manual", "super_auto"):
                await self._transmit()
