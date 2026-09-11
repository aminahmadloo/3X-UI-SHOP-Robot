from aiogram.fsm.state import State, StatesGroup


class AdvertisingStates(StatesGroup):
    waiting_channel = State()
    waiting_campaign_title = State()
    waiting_campaign_body = State()
    waiting_button_title = State()
    waiting_button_url = State()
    waiting_button_color = State()
    waiting_service_selection = State()
    waiting_publication_destinations = State()
    waiting_publication_channels = State()
    waiting_edit_campaign_title = State()
    waiting_edit_campaign_body = State()
    waiting_edit_campaign_media = State()
    waiting_edit_button_title = State()
    waiting_edit_button_url = State()
    waiting_add_button_title = State()
    waiting_add_button_url = State()
    waiting_add_button_color = State()
