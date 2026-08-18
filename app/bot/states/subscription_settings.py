from aiogram.fsm.state import State, StatesGroup


class SubscriptionSettingsStates(StatesGroup):
    waiting_domain = State()
    waiting_port = State()
    waiting_path = State()
