from aiogram.fsm.state import State, StatesGroup


class ConnectedDeviceSettingsStates(StatesGroup):
    waiting_max_devices = State()
