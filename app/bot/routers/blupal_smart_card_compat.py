from __future__ import annotations

from app.bot.payment_gateways.blupal_gateway import BluPalGateway
from app.bot.routers import managed_card_payment
from app.bot.routers.subscription import keyboard as subscription_keyboard
from app.bot.routers.wallet import gateway_payment as wallet_gateway_payment


_original_blupal_success = BluPalGateway.handle_payment_succeeded


async def _blupal_success(self: BluPalGateway, payment_id: str) -> None:
    async with self.session() as db:
        from app.db.models import Transaction
        from app.bot.models import SubscriptionData

        transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
        if transaction is None:
            raise RuntimeError(f"BluPal transaction {payment_id} was not found")
        data = SubscriptionData.deserialize(transaction.subscription)

    if data.payment_kind == "wallet_topup":
        await self.credit_wallet(payment_id)
        return

    await _original_blupal_success(self, payment_id)


BluPalGateway.handle_payment_succeeded = _blupal_success

# managed_card_payment imported these names before the smart integration was
# installed. Keep its legacy/traffic paths functional while using the new
# smart-card selector for the purchase/renewal paths requested in this PR.
managed_card_payment.managed_payment_method_keyboard = subscription_keyboard.managed_payment_method_keyboard
managed_card_payment.managed_payment_method_keyboard_renewal = subscription_keyboard.managed_payment_method_keyboard_renewal
