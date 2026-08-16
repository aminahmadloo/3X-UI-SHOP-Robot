import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsDev
from app.bot.models import ServicesContainer
from app.bot.routers.misc.keyboard import back_keyboard
from app.bot.utils.constants import (
    MAIN_MESSAGE_ID_KEY,
    SERVER_HOST_KEY,
    SERVER_MAX_CLIENTS_KEY,
    SERVER_NAME_KEY,
)
from app.bot.utils.navigation import NavAdminTools
from app.bot.utils.network import ping_url
from app.bot.utils.validation import is_valid_client_count, is_valid_host
from app.db.models import Server, User

from .keyboard import (
    confirm_add_server_keyboard,
    confirm_edit_server_keyboard,
    server_keyboard,
    servers_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name=__name__)

EDIT_ORIGINAL_SERVER_NAME_KEY = "edit_original_server_name"


class AddServerStates(StatesGroup):
    name = State()
    host = State()
    max_clients = State()
    confirmation = State()


class EditServerStates(StatesGroup):
    name = State()
    host = State()
    max_clients = State()
    confirmation = State()


@router.callback_query(F.data == NavAdminTools.SERVER_MANAGEMENT, IsDev())
async def callback_server_management(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    logger.info(f"Dev {user.tg_id} opened servers.")
    await state.set_state(None)
    text = _("server_management:message:main")
    servers = await Server.get_all(session)

    if not servers:
        text += _("server_management:message:empty")

    await callback.message.edit_text(text=text, reply_markup=servers_keyboard(servers))


@router.callback_query(F.data == NavAdminTools.SYNC_SERVERS, IsDev())
async def callback_sync_servers(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    logger.info(f"Dev {user.tg_id} sync servers.")
    await services.server_pool.sync_servers()

    try:
        await callback_server_management(callback=callback, user=user, session=session, state=state)
    except Exception:
        pass

    await services.notification.show_popup(
        callback=callback,
        text=_("server_management:popup:synced"),
    )


# region Add Server
async def show_add_server(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    data = await state.get_data()
    main_message_id = data.get(MAIN_MESSAGE_ID_KEY)

    text = _("server_management:message:add")
    name = _("server_management:message:name").format(server_name=data.get(SERVER_NAME_KEY))
    host = _("server_management:message:host").format(server_host=data.get(SERVER_HOST_KEY))
    max_clients = _("server_management:message:max_clients").format(
        server_max_clients=data.get(SERVER_MAX_CLIENTS_KEY)
    )
    reply_markup = back_keyboard(NavAdminTools.ADD_SERVER_BACK)

    match current_state:
        case AddServerStates.name:
            text += _("server_management:message:enter_name")
            reply_markup = back_keyboard(NavAdminTools.SERVER_MANAGEMENT)
        case AddServerStates.host:
            text += name + "\n"
            text += _("server_management:message:enter_host")
        case AddServerStates.max_clients:
            text += name + host + "\n"
            text += _("server_management:message:enter_max_clients")
        case AddServerStates.confirmation:
            text += name + host + max_clients + "\n"
            text += _("server_management:message:confirm")
            reply_markup = confirm_add_server_keyboard()

    await message.bot.edit_message_text(
        text=text,
        chat_id=message.chat.id,
        message_id=main_message_id,
        reply_markup=reply_markup,
    )


@router.callback_query(StateFilter("*"), F.data == NavAdminTools.ADD_SERVER_BACK, IsDev())
async def callback_add_server_back(callback: CallbackQuery, state: FSMContext) -> None:
    current_state = await state.get_state()

    match current_state:
        case AddServerStates.host:
            await state.set_state(AddServerStates.name)
        case AddServerStates.max_clients:
            await state.set_state(AddServerStates.host)
        case AddServerStates.confirmation:
            await state.set_state(AddServerStates.max_clients)

    await show_add_server(message=callback.message, state=state)


@router.callback_query(F.data == NavAdminTools.ADD_SERVER, IsDev())
async def callback_add_server(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    logger.info(f"Dev {user.tg_id} started adding server.")
    await state.set_state(AddServerStates.name)
    await show_add_server(message=callback.message, state=state)


@router.message(AddServerStates.name, IsDev())
async def message_name(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    server_name = message.text.strip()
    logger.info(f"Dev {user.tg_id} entered server name: {server_name}")
    existing_server = await Server.get_by_name(session=session, name=server_name)

    if not existing_server:
        await state.set_state(AddServerStates.host)
        await state.update_data({SERVER_NAME_KEY: server_name})
        await show_add_server(message=message, state=state)
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("server_management:ntf:name_exists"),
            duration=5,
        )


@router.message(AddServerStates.host, IsDev())
async def message_host(
    message: Message,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    server_host = message.text.strip()
    logger.info(f"Dev {user.tg_id} entered server host: {server_host}")

    if is_valid_host(server_host):
        await state.set_state(AddServerStates.max_clients)
        await state.update_data({SERVER_HOST_KEY: server_host})
        await show_add_server(message=message, state=state)
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("server_management:ntf:invalid_host"),
            duration=5,
        )


@router.message(AddServerStates.max_clients, IsDev())
async def message_max_clients(
    message: Message,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    server_max_clients = message.text.strip()
    logger.info(f"Dev {user.tg_id} entered server max clients: {server_max_clients}")

    if is_valid_client_count(server_max_clients):
        await state.set_state(AddServerStates.confirmation)
        await state.update_data({SERVER_MAX_CLIENTS_KEY: server_max_clients})
        await show_add_server(message=message, state=state)
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("server_management:ntf:invalid_max_clients"),
            duration=5,
        )


@router.callback_query(AddServerStates.confirmation, IsDev())
async def callback_confirmation(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    logger.info(f"Dev {user.tg_id} confirmed adding server.")
    data = await state.get_data()

    server = await Server.create(
        session=session,
        name=data.get(SERVER_NAME_KEY),
        host=data.get(SERVER_HOST_KEY),
        max_clients=data.get(SERVER_MAX_CLIENTS_KEY),
    )

    if server:
        await services.server_pool.sync_servers()
        await state.set_state(None)
        await callback_server_management(callback=callback, user=user, session=session, state=state)
        await services.notification.show_popup(
            callback=callback,
            text=_("server_management:popup:added_success"),
        )

    else:
        await services.notification.show_popup(
            callback=callback,
            text=_("server_management:popup:add_failed"),
        )


# endregion


# region Server
async def show_server_details(
    callback: CallbackQuery,
    server: Server,
) -> None:
    status = (
        _("server_management:message:status_online")
        if server.online
        else _("server_management:message:status_offline")
    )
    text = _("server_management:message:server_info").format(
        server_name=server.name,
        host=server.host,
        status=status,
        clients=server.current_clients,
        max_clients=server.max_clients,
    )
    await callback.message.edit_text(
        text=text,
        reply_markup=server_keyboard(server.name),
    )


@router.callback_query(F.data.startswith(NavAdminTools.SHOW_SERVER), IsDev())
async def callback_show_server(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
) -> None:
    server_name = callback.data.split("_", 2)[2]
    logger.info(f"Dev {user.tg_id} open server {server_name}.")
    server = await Server.get_by_name(session=session, name=server_name)
    if not server:
        return
    await show_server_details(callback=callback, server=server)


# region Edit Server
async def show_edit_server(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    data = await state.get_data()
    main_message_id = data.get(MAIN_MESSAGE_ID_KEY)

    text = _("server_management:message:edit")
    name = _("server_management:message:name").format(server_name=data.get(SERVER_NAME_KEY))
    host = _("server_management:message:host").format(server_host=data.get(SERVER_HOST_KEY))
    max_clients = _("server_management:message:max_clients").format(
        server_max_clients=data.get(SERVER_MAX_CLIENTS_KEY)
    )
    reply_markup = back_keyboard(NavAdminTools.EDIT_SERVER_BACK)

    match current_state:
        case EditServerStates.name:
            text += name + "\n"
            text += _("server_management:message:edit_name")
        case EditServerStates.host:
            text += name + "\n"
            text += host + "\n"
            text += _("server_management:message:edit_host")
        case EditServerStates.max_clients:
            text += name + "\n"
            text += host + "\n"
            text += max_clients + "\n"
            text += _("server_management:message:edit_max_clients")
        case EditServerStates.confirmation:
            text += name + host + max_clients + "\n"
            text += _("server_management:message:edit_confirm")
            reply_markup = confirm_edit_server_keyboard()

    await message.bot.edit_message_text(
        text=text,
        chat_id=message.chat.id,
        message_id=main_message_id,
        reply_markup=reply_markup,
    )


@router.callback_query(F.data == NavAdminTools.EDIT_SERVER_BACK, IsDev())
async def callback_edit_server_back(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data = await state.get_data()
    original_name = data.get(EDIT_ORIGINAL_SERVER_NAME_KEY)
    await state.set_state(None)

    if original_name:
        server = await Server.get_by_name(session=session, name=original_name)
        if server:
            await show_server_details(callback=callback, server=server)
            return

    await callback_server_management(
        callback=callback,
        user=None,
        session=session,
        state=state,
    )


@router.callback_query(F.data.startswith(NavAdminTools.EDIT_SERVER + "_"), IsDev())
async def callback_edit_server(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    server_name = callback.data.split("_", 2)[2]
    server = await Server.get_by_name(session=session, name=server_name)

    if not server:
        return

    logger.info(f"Dev {user.tg_id} started editing server {server_name}.")
    await state.update_data(
        {
            EDIT_ORIGINAL_SERVER_NAME_KEY: server.name,
            SERVER_NAME_KEY: server.name,
            SERVER_HOST_KEY: server.host,
            SERVER_MAX_CLIENTS_KEY: str(server.max_clients),
        }
    )
    await state.set_state(EditServerStates.name)
    await show_edit_server(message=callback.message, state=state)


@router.message(EditServerStates.name, IsDev())
async def message_edit_name(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    server_name = message.text.strip()
    data = await state.get_data()
    original_name = data.get(EDIT_ORIGINAL_SERVER_NAME_KEY)
    existing_server = await Server.get_by_name(session=session, name=server_name)

    if existing_server and existing_server.name != original_name:
        await services.notification.notify_by_message(
            message=message,
            text=_("server_management:ntf:name_exists"),
            duration=5,
        )
        return

    logger.info(f"Dev {user.tg_id} changed server name to {server_name}.")
    await state.update_data({SERVER_NAME_KEY: server_name})
    await state.set_state(EditServerStates.host)
    await show_edit_server(message=message, state=state)


@router.message(EditServerStates.host, IsDev())
async def message_edit_host(
    message: Message,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    server_host = message.text.strip()

    if is_valid_host(server_host):
        logger.info(f"Dev {user.tg_id} changed server host to {server_host}.")
        await state.update_data({SERVER_HOST_KEY: server_host})
        await state.set_state(EditServerStates.max_clients)
        await show_edit_server(message=message, state=state)
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("server_management:ntf:invalid_host"),
            duration=5,
        )


@router.message(EditServerStates.max_clients, IsDev())
async def message_edit_max_clients(
    message: Message,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    server_max_clients = message.text.strip()

    if is_valid_client_count(server_max_clients):
        logger.info(f"Dev {user.tg_id} changed server max clients to {server_max_clients}.")
        await state.update_data({SERVER_MAX_CLIENTS_KEY: server_max_clients})
        await state.set_state(EditServerStates.confirmation)
        await show_edit_server(message=message, state=state)
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("server_management:ntf:invalid_max_clients"),
            duration=5,
        )


@router.callback_query(EditServerStates.confirmation, F.data == NavAdminTools.CONFIRM_EDIT_SERVER, IsDev())
async def callback_confirm_edit_server(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    data = await state.get_data()
    original_name = data.get(EDIT_ORIGINAL_SERVER_NAME_KEY)
    new_name = data.get(SERVER_NAME_KEY)
    new_host = data.get(SERVER_HOST_KEY)
    new_max_clients = data.get(SERVER_MAX_CLIENTS_KEY)

    logger.info(f"Dev {user.tg_id} saving server edit: {original_name} -> {new_name}.")

    server = await Server.update(
        session=session,
        name=original_name,
        **{
            "name": new_name,
            "host": new_host,
            "max_clients": int(new_max_clients),
        },
    )

    if server:
        await services.server_pool.sync_servers()
        await state.set_state(None)
        updated_server = await Server.get_by_name(session=session, name=new_name)
        if updated_server:
            await show_server_details(callback=callback, server=updated_server)
        else:
            await callback_server_management(callback=callback, user=user, session=session, state=state)
        await services.notification.show_popup(
            callback=callback,
            text=_("server_management:popup:edited_success"),
        )
    else:
        await services.notification.show_popup(
            callback=callback,
            text=_("server_management:popup:edit_failed"),
        )


# endregion


@router.callback_query(F.data.startswith(NavAdminTools.PING_SERVER), IsDev())
async def callback_ping_server(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    server_name = callback.data.split("_", 2)[2]
    logger.info(f"Dev {user.tg_id} pinging server {server_name}.")
    server = await Server.get_by_name(session=session, name=server_name)
    if not server:
        return
    ping = await ping_url(server.host)
    if ping:
        await services.notification.show_popup(
            callback=callback,
            text=_("server_management:popup:ping").format(server_name=server_name, ping=ping),
        )
    else:
        await services.notification.show_popup(
            callback=callback,
            text=_("server_management:popup:ping_failed").format(server_name=server_name),
        )


@router.callback_query(F.data.startswith(NavAdminTools.DELETE_SERVER), IsDev())
async def callback_delete_server(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    server_name = callback.data.split("_", 2)[2]
    logger.info(f"Dev {user.tg_id} open server {server_name}.")
    deleted = await Server.delete(session=session, name=server_name)
    await callback_server_management(callback=callback, user=user, session=session, state=state)

    if deleted:
        await services.server_pool.sync_servers()
        await services.notification.show_popup(
            callback=callback,
            text=_("server_management:popup:deleted_success"),
        )
    else:
        await services.notification.show_popup(
            callback=callback,
            text=_("server_management:popup:delete_failed"),
        )


# endregion
