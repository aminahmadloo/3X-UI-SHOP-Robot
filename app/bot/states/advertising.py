from aiogram.fsm.state import State, StatesGroup


class AdvertisingStates(StatesGroup):
    waiting_channel = State()
    waiting_campaign_title = State()
    waiting_campaign_body = State()
