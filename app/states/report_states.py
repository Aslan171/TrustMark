from aiogram.fsm.state import State, StatesGroup


class ReportStates(StatesGroup):
    accused = State()
    amount = State()
    currency = State()
    description = State()
    evidence = State()
    confirm = State()

