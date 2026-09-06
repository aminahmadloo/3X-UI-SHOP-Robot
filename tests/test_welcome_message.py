from app.bot.routers.admin_tools.admin_tools_handler import _validate_welcome_message
from app.db.models.welcome_message_settings import DEFAULT_WELCOME_MESSAGE


def test_default_welcome_message_has_user_placeholder() -> None:
    assert "{first_name}" in DEFAULT_WELCOME_MESSAGE
    assert _validate_welcome_message(DEFAULT_WELCOME_MESSAGE) is None


def test_welcome_message_rejects_unknown_variables() -> None:
    error = _validate_welcome_message("سلام {first_name} {username}")
    assert error is not None
    assert "{username}" in error


def test_welcome_message_requires_first_name_variable() -> None:
    error = _validate_welcome_message("سلام کاربر عزیز")
    assert error is not None
    assert "{first_name}" in error


def test_welcome_message_rejects_empty_text() -> None:
    assert _validate_welcome_message("") is not None
