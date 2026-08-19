# Subscription-specific client data

This change scopes XUI client reads used by My Services and renewal flows to the selected `Subscription` using its `client_id` and assigned server. ClientData now exposes client ID, sub ID, Telegram user ID, flow, and inbound ID. Expiry notifications are evaluated per subscription.