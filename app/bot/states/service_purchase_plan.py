from aiogram.fsm.state import State, StatesGroup


class ServicePurchasePlanStates(StatesGroup):
    waiting_volume = State()
    waiting_duration = State()
    waiting_price = State()
