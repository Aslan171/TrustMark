from aiogram.fsm.state import State, StatesGroup


class AdminFindStates(StatesGroup):
    target = State()


class AdminStatusStates(StatesGroup):
    target = State()
    reason = State()
    trusted_payment_amount = State()
    trusted_payment_currency = State()
    trusted_coverage_percent = State()
    guarantor_reviews = State()
    guarantor_nft_usernames = State()
    guarantor_nft_gifts = State()
    evidence = State()
    confirm = State()


class AdminRemoveStatusStates(StatesGroup):
    target = State()
    confirm = State()


class AdminReportStates(StatesGroup):
    comment = State()
    evidence = State()


class AdminLimitStates(StatesGroup):
    target = State()
    amount = State()


class AdminDeleteEvidenceStates(StatesGroup):
    evidence_id = State()
