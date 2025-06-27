from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):

    waiting_for_broadcast_message = State()
    confirming_broadcast = State()
    waiting_for_promo_details = State()
    waiting_for_promo_edit_details = State()
    waiting_for_user_id_to_ban = State()
    waiting_for_user_id_to_unban = State()

    waiting_for_user_id_for_logs = State()
