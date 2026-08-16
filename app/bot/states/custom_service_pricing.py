from aiogram.fsm.state import State, StatesGroup


class CustomServicePricingStates(StatesGroup):
    waiting_value = State()
