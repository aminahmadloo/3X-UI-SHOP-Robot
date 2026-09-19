from aiogram.fsm.state import State, StatesGroup


class AIContentStates(StatesGroup):
    waiting_exact_topic = State()
