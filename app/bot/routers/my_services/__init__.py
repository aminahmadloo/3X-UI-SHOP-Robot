from . import client_control_handler, handler, traffic_addon_ui, auto_connect, auto_connect_details

client_control_handler.router.include_router(auto_connect_details.router)
client_control_handler.router.include_router(auto_connect.router)

__all__ = [
    "handler",
    "client_control_handler",
    "traffic_addon_ui",
    "auto_connect",
    "auto_connect_details",
]
