import os
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv('API_TOKEN')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

conn = sqlite3.connect('support.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    message_text TEXT NOT NULL,
    department TEXT CHECK(department IN ('programmers', 'sales')) NOT NULL,
    status TEXT CHECK(status IN ('new', 'processing', 'resolved')) DEFAULT 'new',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
''')
conn.commit()

# FAQ вопросы с уникальными ID
faq_questions = [
    {"id": "order", "question": "Как оформить заказ?", 
     "answer": "Для оформления заказа выберите товар → \"Добавить в корзину\" → Перейти в корзину → Оформить заказ."},
    {"id": "status", "question": "Как узнать статус заказа?", 
     "answer": "Войдите в аккаунт → Раздел \"Мои заказы\" → Текущий статус указан в списке."},
    {"id": "cancel", "question": "Как отменить заказ?", 
     "answer": "Напишите в поддержку как можно скорее до отправки заказа."},
    {"id": "damage", "question": "Что делать при повреждении товара?", 
     "answer": "Свяжитесь с поддержкой + фото повреждений → Поможем с обменом/возвратом."},
    {"id": "contact", "question": "Как связаться с поддержкой?", 
     "answer": "Через этого бота или телефон на сайте."},
    {"id": "delivery", "question": "Информация о доставке", 
     "answer": "Способы и сроки указаны на странице оформления заказа."}
]

# Состояния для FSM
class AdminStates(StatesGroup):
    resolving = State()

class UserStates(StatesGroup):
    waiting_for_request = State()

# Функция определения отдела
def detect_department(text):
    text = text.lower()
    if any(word in text for word in ['сайт', 'оплата', 'ошибка']):
        return 'programmers'
    elif any(word in text for word in ['товар', 'доставка', 'возврат']):
        return 'sales'
    return None

# Обработчик команды /start
@dp.message(Command('start'))
async def send_welcome(message: Message):
    kb = [[KeyboardButton(text="FAQ"), KeyboardButton(text="Связь с отделом")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer(
        "Добро пожаловать в службу поддержки магазина \"Продаем все на свете\"!\nВыберите действие:",
        reply_markup=keyboard
    )

# Показ FAQ
@dp.message(F.text == "FAQ")
async def show_faq(message: Message):
    builder = InlineKeyboardBuilder()
    for item in faq_questions:
        builder.add(InlineKeyboardButton(
            text=item["question"],
            callback_data=f"faq_{item['id']}"
        ))
    builder.adjust(2)
    await message.answer("Часто задаваемые вопросы:", reply_markup=builder.as_markup())

# Обработка нажатия на FAQ кнопку
@dp.callback_query(F.data.startswith('faq_'))
async def process_faq(callback: CallbackQuery):
    faq_id = callback.data[4:]
    question = next((item for item in faq_questions if item["id"] == faq_id), None)
    if question:
        await callback.message.answer(
            f"<b>Вопрос:</b> {question['question']}\n\n"
            f"<b>Ответ:</b> {question['answer']}",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.answer("Информация не найдена")

# Выбор отдела
@dp.message(F.text == "Связь с отделом")
async def select_department(message: Message, state: FSMContext):
    kb = [
        [KeyboardButton(text="Техническая поддержка"), KeyboardButton(text="Отдел продаж")],
        [KeyboardButton(text="Назад")]
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer("Выберите отдел:", reply_markup=keyboard)
    await state.set_state(UserStates.waiting_for_request)

# Возврат к главному меню
@dp.message(F.text == "Назад", StateFilter(UserStates.waiting_for_request))
async def go_back(message: Message, state: FSMContext):
    await state.clear()
    await send_welcome(message)

# Выбор отдела для обращения
@dp.message(F.text.in_(["Техническая поддержка", "Отдел продаж"]), StateFilter(UserStates.waiting_for_request))
async def process_department(message: Message, state: FSMContext):
    department = 'programmers' if message.text == "Техническая поддержка" else 'sales'
    await state.update_data(department=department)
    await message.answer(
        f"Введите ваш запрос для {message.text}:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Отмена")]],
            resize_keyboard=True
        )
    )

# Отмена запроса
@dp.message(F.text == "Отмена", StateFilter(UserStates.waiting_for_request))
async def cancel_request(message: Message, state: FSMContext):
    await state.clear()
    await send_welcome(message)

# Сохранение запроса
@dp.message(StateFilter(UserStates.waiting_for_request))
async def save_request(message: Message, state: FSMContext):
    data = await state.get_data()
    department = data.get('department')
    
    if not department:
        await message.answer("Ошибка определения отдела. Попробуйте снова.")
        await state.clear()
        return
    
    cursor.execute(
        "INSERT INTO requests (user_id, message_text, department) VALUES (?, ?, ?)",
        (message.from_user.id, message.text, department)
    )
    conn.commit()
    
    await message.answer(f"Запрос передан в {department}! Ожидайте ответа.")
    await bot.send_message(ADMIN_CHAT_ID, f"Новый запрос в {department} от {message.from_user.id}:\n{message.text}")
    await state.clear()

# Просмотр активных запросов администратором
@dp.message(Command('requests'))
async def show_requests(message: Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Нет доступа")
        return
    
    cursor.execute("SELECT * FROM requests WHERE status != 'resolved'")
    requests = cursor.fetchall()
    
    if not requests:
        await message.answer("Нет активных запросов")
        return
    
    response = "Активные запросы:\n\n"
    for req in requests:
        response += f"ID: {req[0]}\n"
        response += f"От: {req[1]}\n"
        response += f"Текст: {req[2]}\n"
        response += f"Отдел: {req[3]}\n"
        response += f"Статус: {req[4]}\n"
        response += f"Дата: {req[5]}\n"
        response += "--------------------\n"
    
    await message.answer(response)

# Решение запроса администратором
@dp.message(Command('resolve'))
async def resolve_request(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("Нет доступа")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /resolve <ID>")
        return
    
    request_id = args[1]
    await state.update_data(request_id=request_id)
    await message.answer(f"Введите ответ для запроса {request_id}:")
    await state.set_state(AdminStates.resolving)

# Обработка ответа на запрос
@dp.message(StateFilter(AdminStates.resolving))
async def process_resolve(message: Message, state: FSMContext):
    data = await state.get_data()
    request_id = data.get('request_id')
    
    cursor.execute("UPDATE requests SET status = 'resolved' WHERE id = ?", (request_id,))
    conn.commit()
    
    cursor.execute("SELECT user_id FROM requests WHERE id = ?", (request_id,))
    user_id = cursor.fetchone()[0]
    
    await bot.send_message(user_id, f"Ваш запрос решен:\n\n{message.text}")
    await message.answer(f"Запрос {request_id} закрыт")
    await state.clear()

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
