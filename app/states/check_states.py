from aiogram.fsm.state import State, StatesGroup


class CheckStates(StatesGroup):
    waiting_target = State()

