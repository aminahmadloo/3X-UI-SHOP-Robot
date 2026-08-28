from aiogram.fsm.state import State, StatesGroup


class TestAccountSettingsStates(StatesGroup):
    waiting_volume_mb = State()
    waiting_duration_days = State()
    waiting_cleanup_interval_hours = State()
