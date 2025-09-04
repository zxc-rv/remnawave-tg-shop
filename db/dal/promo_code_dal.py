import logging
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, func, and_, or_
from datetime import datetime, timezone

from db.models import PromoCode, PromoCodeActivation, User, Payment


async def create_promo_code(session: AsyncSession,
                            promo_data: Dict[str, Any]) -> PromoCode:

    new_promo = PromoCode(**promo_data)
    session.add(new_promo)
    await session.flush()
    await session.refresh(new_promo)
    logging.info(
        f"Promo code '{new_promo.code}' created with ID {new_promo.promo_code_id}"
    )
    return new_promo


async def get_promo_code_by_id(session: AsyncSession,
                               promo_code_id: int) -> Optional[PromoCode]:
    return await session.get(PromoCode, promo_code_id)


async def get_active_promo_code_by_code_str(
        session: AsyncSession, code_str: str) -> Optional[PromoCode]:
    stmt = select(PromoCode).where(
        PromoCode.code == code_str.upper(), PromoCode.is_active == True,
        PromoCode.current_activations < PromoCode.max_activations,
        or_(PromoCode.valid_until == None, PromoCode.valid_until
            > datetime.now(timezone.utc)))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_all_active_promo_codes(session: AsyncSession,
                                     limit: int = 20,
                                     offset: int = 0) -> List[PromoCode]:
    stmt = (select(PromoCode).where(
        PromoCode.is_active == True,
        or_(PromoCode.valid_until == None, PromoCode.valid_until
            > datetime.now(timezone.utc))).order_by(
                PromoCode.created_at.desc()).limit(limit).offset(offset))
    result = await session.execute(stmt)
    return result.scalars().all()


async def update_promo_code(session: AsyncSession, promo_id: int,
                            update_data: Dict[str, Any]) -> Optional[PromoCode]:
    promo = await get_promo_code_by_id(session, promo_id)
    if not promo:
        return None
    for key, value in update_data.items():
        setattr(promo, key, value)
    await session.flush()
    await session.refresh(promo)
    return promo


async def delete_promo_code(session: AsyncSession, promo_id: int) -> Optional[PromoCode]:
    promo = await get_promo_code_by_id(session, promo_id)
    if not promo:
        return None
    await session.delete(promo)
    await session.flush()
    return promo


async def increment_promo_code_usage(
        session: AsyncSession, promo_code_id: int) -> Optional[PromoCode]:
    promo = await get_promo_code_by_id(session, promo_code_id)
    if promo:
        if promo.current_activations < promo.max_activations:
            promo.current_activations += 1
            await session.flush()
            await session.refresh(promo)
            return promo
        else:
            logging.warning(
                f"Promo code {promo.code} (ID: {promo_code_id}) already reached max activations."
            )
            return None
    return None


async def get_user_activation_for_promo(
        session: AsyncSession, promo_code_id: int,
        user_id: int) -> Optional[PromoCodeActivation]:

    stmt = select(PromoCodeActivation).where(
        PromoCodeActivation.promo_code_id == promo_code_id,
        PromoCodeActivation.user_id == user_id).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def record_promo_activation(
        session: AsyncSession,
        promo_code_id: int,
        user_id: int,
        payment_id: Optional[int] = None) -> Optional[PromoCodeActivation]:

    existing_activation = await get_user_activation_for_promo(
        session, promo_code_id, user_id)
    if existing_activation:
        logging.info(
            f"User {user_id} has already activated promo code {promo_code_id}. Activation ID: {existing_activation.activation_id}"
        )
        return existing_activation

    from .user_dal import get_user_by_id
    user = await get_user_by_id(session, user_id)
    promo = await get_promo_code_by_id(session, promo_code_id)
    if not user or not promo:
        logging.error(
            f"Cannot record promo activation: User {user_id} or Promo {promo_code_id} not found."
        )
        return None

    if payment_id:
        from .payment_dal import get_payment_by_db_id
        payment = await get_payment_by_db_id(session, payment_id)
        if not payment:
            logging.error(
                f"Cannot record promo activation: Payment {payment_id} not found."
            )

            return None

    activation_data = {
        "promo_code_id": promo_code_id,
        "user_id": user_id,
        "payment_id": payment_id,
        "activated_at": datetime.now(timezone.utc)
    }
    new_activation = PromoCodeActivation(**activation_data)
    session.add(new_activation)
    await session.flush()
    await session.refresh(new_activation)
    logging.info(
        f"Promo code {promo_code_id} activated by user {user_id}. Activation ID: {new_activation.activation_id}"
    )
    return new_activation
