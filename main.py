import asyncio
import logging
import os
import requests
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, 
                          InlineKeyboardButton)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Токены и настройки
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8326095098:AAHVE8r5qaS8V2raYQgvi1Gz9dPEbUZ9ll8")
HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")

# НАСТРОЙКИ КАНАЛОВ ДЛЯ ПОДПИСКИ (ТВОИ КАНАЛЫ!)
REQUIRED_CHANNELS = [
    {
        "id": os.getenv("CHANNEL_1", "@kanal1kkal"), 
        "url": "https://t.me/kanal1kkal", 
        "name": "🏛️ Artemius AI",
        "description": "Главный канал искусственного интеллекта"
    },
    {
        "id": os.getenv("CHANNEL_2", "@kanal2kkal"), 
        "url": "https://t.me/kanal2kkal", 
        "name": "📢 AI Новости",
        "description": "Новости и обновления AI технологий"
    }
]

# Инициализация
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Состояния FSM
class BotStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_image_prompt = State()
    waiting_for_music_prompt = State()
    waiting_for_video_prompt = State()
    waiting_for_document = State()

# ЛИМИТЫ: малые для базового доступа, хорошие для VIP
FREE_LIMITS = {
    'chat': 3,         # Только 3 диалога без подписки
    'images': 1,       # Только 1 картинка без подписки
    'music': 1,        # Только 1 музыка без подписки
    'video': 1,        # Только 1 видео без подписки
    'documents': 2     # Только 2 документа без подписки
}

VIP_LIMITS = {         # VIP лимиты при подписке на ОБА канала
    'chat': 25,        # 25 диалогов для VIP
    'images': 10,      # 10 картинок для VIP
    'music': 5,        # 5 композиций для VIP
    'video': 3,        # 3 видео для VIP
    'documents': 8     # 8 документов для VIP
}

# Кэш статуса подписки
subscription_cache = {}
user_stats = {}
user_limits = {}

async def check_subscription(user_id: int) -> bool:
    """Проверить подписку на ВСЕ каналы (нужны все для VIP)"""
    try:
        # Проверяем кэш (действует 5 минут)
        now = datetime.now()
        if user_id in subscription_cache:
            cached_time, is_subscribed = subscription_cache[user_id]
            if (now - cached_time).total_seconds() < 300:  # 5 минут
                return is_subscribed

        # Проверяем подписки на все каналы
        all_subscribed = True
        for channel in REQUIRED_CHANNELS:
            try:
                member = await bot.get_chat_member(channel["id"], user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    all_subscribed = False
                    break
            except:
                all_subscribed = False
                break

        # Сохраняем в кэш
        subscription_cache[user_id] = (now, all_subscribed)
        return all_subscribed

    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

async def check_individual_subscriptions(user_id: int) -> Dict[str, bool]:
    """Проверить подписку на каждый канал отдельно"""
    try:
        subscriptions = {}
        for channel in REQUIRED_CHANNELS:
            try:
                member = await bot.get_chat_member(channel["id"], user_id)
                subscriptions[channel["id"]] = member.status in ['member', 'administrator', 'creator']
            except:
                subscriptions[channel["id"]] = False
        return subscriptions
    except:
        return {ch["id"]: False for ch in REQUIRED_CHANNELS}

def get_user_stats(user_id: int) -> dict:
    """Получить статистику пользователя"""
    if user_id not in user_stats:
        user_stats[user_id] = {
            'total_messages': 0,
            'total_images': 0,
            'total_music': 0,
            'total_videos': 0,
            'total_documents': 0,
            'first_seen': datetime.now().isoformat()
        }
    return user_stats[user_id]

def get_daily_usage(user_id: int) -> dict:
    """Получить использование за сегодня"""
    today = datetime.now().date().isoformat()
    if user_id not in user_limits:
        user_limits[user_id] = {}
    if today not in user_limits[user_id]:
        user_limits[user_id][today] = {
            'chat': 0,
            'images': 0,
            'music': 0,
            'video': 0,
            'documents': 0
        }
    return user_limits[user_id][today]

async def check_limit(user_id: int, feature: str) -> bool:
    """Проверить лимит с учетом VIP статуса"""
    is_vip = await check_subscription(user_id)
    daily = get_daily_usage(user_id)

    # Выбираем лимиты в зависимости от VIP статуса
    limits = VIP_LIMITS if is_vip else FREE_LIMITS

    return daily[feature] < limits[feature]

def use_feature(user_id: int, feature: str):
    """Засчитать использование функции"""
    daily = get_daily_usage(user_id)
    daily[feature] += 1

    stats = get_user_stats(user_id)
    stats[f'total_{feature}'] = stats.get(f'total_{feature}', 0) + 1

# Клавиатуры
async def get_main_menu(user_id: int):
    """Главное меню с указанием статуса"""
    is_vip = await check_subscription(user_id)
    status_emoji = "⭐" if is_vip else "🔒"
    status_text = "VIP режим" if is_vip else "Базовый доступ"

    keyboard = [
        [KeyboardButton(text="💬 Чат с Artemius"), KeyboardButton(text="🎨 Создать картинку")],
        [KeyboardButton(text="🎵 Создать песню"), KeyboardButton(text="🎬 Создать видео")],
        [KeyboardButton(text="📄 Документ"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text=f"{status_emoji} {status_text}"), KeyboardButton(text="📢 Получить VIP")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

async def get_subscription_menu(user_id: int):
    """Улучшенное меню подписки с отдельными кнопками для каждого канала"""
    individual_subs = await check_individual_subscriptions(user_id)

    keyboard = []

    # Отдельные кнопки для каждого канала со статусом
    for channel in REQUIRED_CHANNELS:
        is_subscribed = individual_subs.get(channel["id"], False)
        status_emoji = "✅" if is_subscribed else "📢"
        status_text = "Подписан" if is_subscribed else "Подписаться"

        keyboard.append([InlineKeyboardButton(
            text=f"{status_emoji} {channel['name']} • {status_text}", 
            url=channel["url"]
        )])

    # Разделитель
    keyboard.append([InlineKeyboardButton(text="➖ ➖ ➖ ➖ ➖", callback_data="separator")])

    # Кнопка проверки подписок
    keyboard.append([InlineKeyboardButton(
        text="🔄 Проверить подписки и получить VIP", 
        callback_data="check_subscriptions"
    )])

    # Кнопка пропуска
    keyboard.append([InlineKeyboardButton(
        text="⏭️ Продолжить с базовым доступом", 
        callback_data="skip_subscriptions"
    )])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_back_menu():
    """Меню возврата"""
    keyboard = [[KeyboardButton(text="🏠 Главное меню")]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# Обработчик /start
@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    """Стартовое сообщение с проверкой подписки"""
    await state.clear()
    user_id = message.from_user.id
    is_vip = await check_subscription(user_id)

    if is_vip:
        # VIP приветствие
        welcome_text = f"""🏛️ **Добро пожаловать, VIP-пользователь!**

⭐ **VIP СТАТУС АКТИВЕН!**
Спасибо за подписку на наши каналы!

🚀 **ВАШИ VIP-ЛИМИТЫ:**
💬 Диалоги — **{VIP_LIMITS['chat']} в день**
🎨 Картинки — **{VIP_LIMITS['images']} в день**  
🎵 Музыка — **{VIP_LIMITS['music']} в день**
🎬 Видео — **{VIP_LIMITS['video']} в день**
📄 Документы — **{VIP_LIMITS['documents']} в день**

✨ **Передовые AI технологии:**
• DeepSeek V3 для умных диалогов
• Stable Diffusion для изображений
• MusicGen для музыки
• Video AI для роликов
• TrOCR для документов

Наслаждайтесь VIP-возможностями! 🎯"""

        reply_markup = await get_main_menu(user_id)

    else:
        # Обычное приветствие с призывом к подписке
        welcome_text = f"""🏛️ **Добро пожаловать в Artemius AI!**

🤖 Я ваш персональный ИИ-помощник с множеством возможностей!

🔒 **ВАШИ ТЕКУЩИЕ ЛИМИТЫ (базовый доступ):**
💬 Диалоги — **{FREE_LIMITS['chat']} в день**
🎨 Картинки — **{FREE_LIMITS['images']} в день**  
🎵 Музыка — **{FREE_LIMITS['music']} в день**
🎬 Видео — **{FREE_LIMITS['video']} в день**
📄 Документы — **{FREE_LIMITS['documents']} в день**

⭐ **ХОТИТЕ ПОЛУЧИТЬ VIP СТАТУС?**
Подпишитесь на наши каналы и получите:

💬 **{VIP_LIMITS['chat']} диалогов** в день (сейчас {FREE_LIMITS['chat']})
🎨 **{VIP_LIMITS['images']} картинок** в день (сейчас {FREE_LIMITS['images']})
🎵 **{VIP_LIMITS['music']} композиций** в день (сейчас {FREE_LIMITS['music']})
🎬 **{VIP_LIMITS['video']} видео** в день (сейчас {FREE_LIMITS['video']})
📄 **{VIP_LIMITS['documents']} документов** в день (сейчас {FREE_LIMITS['documents']})

🚀 **Подпишитесь на оба канала для получения VIP!**"""

        reply_markup = await get_subscription_menu(user_id)

    await message.answer(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

# ОБНОВЛЕННАЯ функция уведомлений при исчерпании лимитов
async def show_limit_exhausted(message: types.Message, feature: str):
    """Показать сообщение об исчерпании лимита с четким призывом к подписке"""
    user_id = message.from_user.id
    is_vip = await check_subscription(user_id)

    feature_names = {
        'chat': 'диалогов с Artemius',
        'images': 'генераций изображений',
        'music': 'создания музыки', 
        'video': 'видеопроизводства',
        'documents': 'анализа документов'
    }

    feature_emoji = {
        'chat': '💬',
        'images': '🎨',
        'music': '🎵',
        'video': '🎬',
        'documents': '📄'
    }

    current_limit = VIP_LIMITS[feature] if is_vip else FREE_LIMITS[feature]
    vip_limit = VIP_LIMITS[feature]

    if is_vip:
        # Для VIP пользователей - простое уведомление
        text = f"""🚫 **Вы исчерпали лимит {feature_names[feature]}!**

⭐ **VIP статус:** {current_limit} в день
⏰ **Лимиты обновятся:** завтра в 00:00 МСК

💡 А пока можете использовать другие функции Artemius!"""

        await message.answer(text, parse_mode="Markdown")

    else:
        # Для обычных пользователей - призыв к подписке  
        increase = vip_limit - current_limit

        text = f"""🚫 **Вы исчерпали лимит {feature_names[feature]}!**

{feature_emoji[feature]} **Текущий лимит:** {current_limit} в день

⭐ **Чтобы получить VIP статус, подпишитесь на каналы!**

🎯 **VIP лимит:** {vip_limit} в день (+{increase} дополнительно!)

🚀 **ВСЕ VIP БОНУСЫ:**
💬 {VIP_LIMITS['chat']} диалогов (+{VIP_LIMITS['chat'] - FREE_LIMITS['chat']})
🎨 {VIP_LIMITS['images']} картинок (+{VIP_LIMITS['images'] - FREE_LIMITS['images']})
🎵 {VIP_LIMITS['music']} композиций (+{VIP_LIMITS['music'] - FREE_LIMITS['music']})
🎬 {VIP_LIMITS['video']} видео (+{VIP_LIMITS['video'] - FREE_LIMITS['video']})
📄 {VIP_LIMITS['documents']} документов (+{VIP_LIMITS['documents'] - FREE_LIMITS['documents']})

📢 **Подпишитесь на оба канала прямо сейчас!**"""

        await message.answer(text, reply_markup=await get_subscription_menu(user_id), parse_mode="Markdown")

# Обработчики основных функций
@dp.message(F.text == "💬 Чат с Artemius")
async def chat_handler(message: types.Message, state: FSMContext):
    """Чат с проверкой лимитов"""
    user_id = message.from_user.id
    is_vip = await check_subscription(user_id)

    if not await check_limit(user_id, 'chat'):
        await show_limit_exhausted(message, 'chat')
        return

    await state.set_state(BotStates.waiting_for_text)
    daily = get_daily_usage(user_id)
    limits = VIP_LIMITS if is_vip else FREE_LIMITS
    remaining = limits['chat'] - daily['chat']

    status = "VIP" if is_vip else "Базовый"

    await message.answer(
        f"🏛️ **Artemius готов к диалогу!**\n\n"
        f"⭐ **Статус:** {status} доступ\n"
        f"💡 **Осталось сообщений:** {remaining}\n\n"
        f"🧠 Задавайте любые вопросы — я помогу с программированием, творчеством, решением задач и многим другим!",
        reply_markup=get_back_menu(),
        parse_mode="Markdown"
    )

@dp.message(F.text == "🎨 Создать картинку")
async def image_handler(message: types.Message, state: FSMContext):
    """Генерация изображений с проверкой лимитов"""
    user_id = message.from_user.id
    is_vip = await check_subscription(user_id)

    if not await check_limit(user_id, 'images'):
        await show_limit_exhausted(message, 'images')
        return

    await state.set_state(BotStates.waiting_for_image_prompt)
    daily = get_daily_usage(user_id)
    limits = VIP_LIMITS if is_vip else FREE_LIMITS
    remaining = limits['images'] - daily['images']

    status = "VIP" if is_vip else "Базовый"

    await message.answer(
        f"🎨 **Artemius Art Studio активирован!**\n\n"
        f"⭐ **Статус:** {status} доступ\n"
        f"💡 **Осталось изображений:** {remaining}\n\n"
        f"🖼️ **Примеры запросов:**\n"
        f"• Мистический лес с волшебными созданиями\n"
        f"• Киберпанк город с неоновыми огнями\n"
        f"• Портрет эльфа в стиле фэнтези\n"
        f"• Космический корабль среди звезд\n\n"
        f"Опишите что создать:",
        reply_markup=get_back_menu(),
        parse_mode="Markdown"
    )

@dp.message(F.text == "🎵 Создать песню")
async def music_handler(message: types.Message, state: FSMContext):
    """Создание музыки с проверкой лимитов"""
    user_id = message.from_user.id
    is_vip = await check_subscription(user_id)

    if not await check_limit(user_id, 'music'):
        await show_limit_exhausted(message, 'music')
        return

    await state.set_state(BotStates.waiting_for_music_prompt)
    daily = get_daily_usage(user_id)
    limits = VIP_LIMITS if is_vip else FREE_LIMITS
    remaining = limits['music'] - daily['music']

    status = "VIP" if is_vip else "Базовый"

    await message.answer(
        f"🎵 **Artemius Music Composer активирован!**\n\n"
        f"⭐ **Статус:** {status} доступ\n"
        f"💡 **Осталось композиций:** {remaining}\n\n"
        f"🎼 **Примеры запросов:**\n"
        f"• Эпичная оркестровая музыка для фильма\n"
        f"• Расслабляющий джаз для работы\n"
        f"• Энергичная электронная музыка для спорта\n"
        f"• Романтическая мелодия с пианино\n\n"
        f"Опишите какую музыку создать:",
        reply_markup=get_back_menu(),
        parse_mode="Markdown"
    )

@dp.message(F.text == "🎬 Создать видео")
async def video_handler(message: types.Message, state: FSMContext):
    """Создание видео с проверкой лимитов"""
    user_id = message.from_user.id
    is_vip = await check_subscription(user_id)

    if not await check_limit(user_id, 'video'):
        await show_limit_exhausted(message, 'video')
        return

    await state.set_state(BotStates.waiting_for_video_prompt)
    daily = get_daily_usage(user_id)
    limits = VIP_LIMITS if is_vip else FREE_LIMITS
    remaining = limits['video'] - daily['video']

    status = "VIP" if is_vip else "Базовый"

    await message.answer(
        f"🎬 **Artemius Video Producer активирован!**\n\n"
        f"⭐ **Статус:** {status} доступ\n"
        f"💡 **Осталось видео:** {remaining}\n\n"
        f"🎥 **Доступные AI сервисы:**\n"
        f"🌊 **Veo 3** — реалистичные сцены природы\n"
        f"🤖 **Kling AI** — быстрая HD генерация\n"
        f"🧡 **Hailuo 02** — креативные эффекты\n"
        f"🐰 **Pika 2.2** — профессиональное качество\n\n"
        f"📱 **Параметры:** HD (720p-1080p) • 5-10 сек\n\n"
        f"Опишите какое видео создать:",
        reply_markup=get_back_menu(),
        parse_mode="Markdown"
    )

@dp.message(F.text == "📄 Документ")
async def document_handler(message: types.Message, state: FSMContext):
    """Анализ документов с проверкой лимитов"""
    user_id = message.from_user.id
    is_vip = await check_subscription(user_id)

    if not await check_limit(user_id, 'documents'):
        await show_limit_exhausted(message, 'documents')
        return

    await state.set_state(BotStates.waiting_for_document)
    daily = get_daily_usage(user_id)
    limits = VIP_LIMITS if is_vip else FREE_LIMITS
    remaining = limits['documents'] - daily['documents']

    status = "VIP" if is_vip else "Базовый"

    await message.answer(
        f"📄 **Artemius Document Analyzer активирован!**\n\n"
        f"⭐ **Статус:** {status} доступ\n"
        f"💡 **Осталось анализов:** {remaining}\n\n"
        f"🔍 **Artemius умеет обрабатывать:**\n"
        f"• Сканы документов и справок\n"
        f"• Рукописные заметки и тексты\n"
        f"• Чеки, счета и квитанции\n"
        f"• Таблицы и формы\n\n"
        f"📸 Отправьте фото документа:",
        reply_markup=get_back_menu(),
        parse_mode="Markdown"
    )

@dp.message(F.text == "👤 Мой профиль")
async def profile_handler(message: types.Message):
    """Показать профиль пользователя"""
    user_id = message.from_user.id
    is_vip = await check_subscription(user_id)
    stats = get_user_stats(user_id)
    daily = get_daily_usage(user_id)

    limits = VIP_LIMITS if is_vip else FREE_LIMITS

    if is_vip:
        status_title = "⭐ VIP СТАТУС АКТИВЕН!"
        status_desc = "Спасибо за подписку на каналы!"
    else:
        status_title = "🔒 БАЗОВЫЙ ДОСТУП"
        status_desc = "Подпишитесь на каналы для VIP статуса!"

    profile_text = f"""👤 **Профиль пользователя Artemius AI**

{status_title}
{status_desc}

📊 **Использовано сегодня:**
💬 Диалоги: {daily['chat']}/{limits['chat']}
🎨 Изображения: {daily['images']}/{limits['images']}  
🎵 Музыка: {daily['music']}/{limits['music']}
🎬 Видео: {daily['video']}/{limits['video']}
📄 Документы: {daily['documents']}/{limits['documents']}

📈 **Всего создано с Artemius:**
• Диалогов: {stats['total_messages']:,}
• Изображений: {stats['total_images']:,}
• Композиций: {stats['total_music']:,}
• Видеороликов: {stats['total_videos']:,}
• Документов: {stats['total_documents']:,}

⏰ Лимиты обновляются каждый день в 00:00 МСК"""

    if not is_vip:
        profile_text += f"""

⭐ **ПОЛУЧИТЕ VIP СТАТУС:**
Подпишитесь на оба канала и получите:

💬 {VIP_LIMITS['chat']} диалогов (+{VIP_LIMITS['chat'] - FREE_LIMITS['chat']})
🎨 {VIP_LIMITS['images']} картинок (+{VIP_LIMITS['images'] - FREE_LIMITS['images']})
🎵 {VIP_LIMITS['music']} композиций (+{VIP_LIMITS['music'] - FREE_LIMITS['music']})
🎬 {VIP_LIMITS['video']} видео (+{VIP_LIMITS['video'] - FREE_LIMITS['video']})
📄 {VIP_LIMITS['documents']} документов (+{VIP_LIMITS['documents'] - FREE_LIMITS['documents']})

🚀 Подпишитесь на каналы!"""

    reply_markup = None if is_vip else await get_subscription_menu(user_id)
    await message.answer(profile_text, reply_markup=reply_markup, parse_mode="Markdown")

@dp.message(F.text.in_(["⭐ VIP режим", "🔒 Базовый доступ", "📢 Получить VIP"]))
async def subscription_info_handler(message: types.Message):
    """Информация о получении VIP статуса"""
    user_id = message.from_user.id
    is_vip = await check_subscription(user_id)

    if is_vip:
        await message.answer(
            f"⭐ **VIP СТАТУС УЖЕ АКТИВЕН!**\n\n"
            f"Спасибо за поддержку наших каналов!\n\n"
            f"🎯 **Ваши VIP-лимиты:**\n"
            f"💬 {VIP_LIMITS['chat']} диалогов в день\n"
            f"🎨 {VIP_LIMITS['images']} изображений в день\n"
            f"🎵 {VIP_LIMITS['music']} композиций в день\n"
            f"🎬 {VIP_LIMITS['video']} видеороликов в день\n"
            f"📄 {VIP_LIMITS['documents']} анализов документов в день\n\n"
            f"🏛️ Наслаждайтесь возможностями Artemius AI!",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"⭐ **КАК ПОЛУЧИТЬ VIP СТАТУС?**\n\n"
            f"📢 **Подпишитесь на ОБА наших канала:**\n\n"
            + "\n".join([f"• {ch['name']} — {ch['description']}" for ch in REQUIRED_CHANNELS]) +
            f"\n\n🚀 **Что вы получите:**\n\n"
            f"**СЕЙЧАС (базовый):**\n"
            f"💬 {FREE_LIMITS['chat']} диалогов в день\n"
            f"🎨 {FREE_LIMITS['images']} изображений в день\n"
            f"🎵 {FREE_LIMITS['music']} композиций в день\n"
            f"🎬 {FREE_LIMITS['video']} видео в день\n"
            f"📄 {FREE_LIMITS['documents']} документов в день\n\n"
            f"**ПОСЛЕ ПОДПИСКИ (VIP):**\n"
            f"💬 **{VIP_LIMITS['chat']} диалогов** (+{VIP_LIMITS['chat'] - FREE_LIMITS['chat']})\n"
            f"🎨 **{VIP_LIMITS['images']} изображений** (+{VIP_LIMITS['images'] - FREE_LIMITS['images']})\n"
            f"🎵 **{VIP_LIMITS['music']} композиций** (+{VIP_LIMITS['music'] - FREE_LIMITS['music']})\n"
            f"🎬 **{VIP_LIMITS['video']} видео** (+{VIP_LIMITS['video'] - FREE_LIMITS['video']})\n"
            f"📄 **{VIP_LIMITS['documents']} документов** (+{VIP_LIMITS['documents'] - FREE_LIMITS['documents']})\n\n"
            f"⭐ **Подпишитесь на каналы прямо сейчас!**",
            reply_markup=await get_subscription_menu(user_id),
            parse_mode="Markdown"
        )

# Обработка коллбеков
@dp.callback_query(F.data == "separator")
async def separator_callback(callback: types.CallbackQuery):
    """Игнорируем нажатие на разделитель"""
    await callback.answer()

@dp.callback_query(F.data == "check_subscriptions")
async def check_subscriptions_callback(callback: types.CallbackQuery):
    """Проверить подписки пользователя"""
    await callback.answer("🔄 Проверяю подписки...")
    user_id = callback.from_user.id

    # Очищаем кэш для принудительной проверки
    if user_id in subscription_cache:
        del subscription_cache[user_id]

    is_vip = await check_subscription(user_id)
    individual_subs = await check_individual_subscriptions(user_id)

    if is_vip:
        await callback.message.answer(
            f"✅ **ПОЗДРАВЛЯЕМ! VIP СТАТУС АКТИВИРОВАН!**\n\n"
            f"🎉 Спасибо за подписку на оба канала!\n\n"
            f"⭐ **Ваши новые VIP-лимиты:**\n"
            f"💬 {VIP_LIMITS['chat']} диалогов в день\n"
            f"🎨 {VIP_LIMITS['images']} изображений в день\n"
            f"🎵 {VIP_LIMITS['music']} композиций в день\n"
            f"🎬 {VIP_LIMITS['video']} видеороликов в день\n"
            f"📄 {VIP_LIMITS['documents']} документов в день\n\n"
            f"🚀 Теперь у вас есть доступ к расширенным возможностям Artemius AI!",
            reply_markup=await get_main_menu(user_id),
            parse_mode="Markdown"
        )
    else:
        # Показываем какие каналы подписаны, какие нет
        subscribed_channels = []
        missing_channels = []

        for channel in REQUIRED_CHANNELS:
            if individual_subs.get(channel["id"], False):
                subscribed_channels.append(f"✅ {channel['name']}")
            else:
                missing_channels.append(f"❌ {channel['name']}")

        status_text = "\n".join(subscribed_channels + missing_channels)

        if missing_channels:
            await callback.message.answer(
                f"❌ **VIP статус пока недоступен**\n\n"
                f"📊 **Статус подписок:**\n"
                f"{status_text}\n\n"
                f"📢 **Для получения VIP нужно подписаться на ВСЕ каналы!**\n\n"
                f"🔍 Убедитесь что вы:\n"
                f"• Подписались на все каналы\n"
                f"• НЕ заблокировали каналы\n"
                f"• Подождали 1-2 минуты после подписки\n\n"
                f"🔄 Подпишитесь и попробуйте еще раз!",
                reply_markup=await get_subscription_menu(user_id),
                parse_mode="Markdown"
            )
        else:
            await callback.message.answer(
                f"⏳ **Проверяем подписки...**\n\n"
                f"Возможно нужно подождать минуту для обновления статуса.\n"
                f"Попробуйте еще раз через 30-60 секунд.",
                reply_markup=await get_subscription_menu(user_id),
                parse_mode="Markdown"
            )

@dp.callback_query(F.data == "skip_subscriptions")
async def skip_subscriptions_callback(callback: types.CallbackQuery):
    """Пропустить подписку (пока что)"""
    await callback.answer()
    user_id = callback.from_user.id

    await callback.message.answer(
        f"🔒 **Базовый доступ активен**\n\n"
        f"Вы можете пользоваться ограниченными возможностями:\n\n"
        f"💬 {FREE_LIMITS['chat']} диалогов в день\n"
        f"🎨 {FREE_LIMITS['images']} изображений в день\n"
        f"🎵 {FREE_LIMITS['music']} композиций в день\n"
        f"🎬 {FREE_LIMITS['video']} видео в день\n"
        f"📄 {FREE_LIMITS['documents']} документов в день\n\n"
        f"⭐ **В любой момент можете получить VIP**, подписавшись на каналы!",
        reply_markup=await get_main_menu(user_id),
        parse_mode="Markdown"
    )

@dp.message(F.text == "🏠 Главное меню")
async def main_menu_handler(message: types.Message, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()
    user_id = message.from_user.id
    is_vip = await check_subscription(user_id)

    status = "VIP режим" if is_vip else "Базовый доступ"

    await message.answer(
        f"🏛️ **Artemius AI — Главное меню**\n\n⭐ **Текущий статус:** {status}", 
        reply_markup=await get_main_menu(user_id),
        parse_mode="Markdown"
    )

# AI ФУНКЦИИ (упрощенные версии для демонстрации)
async def chat_with_ai(prompt: str, user_id: int) -> str:
    """Чат с AI"""
    try:
        use_feature(user_id, 'chat')
        return f"🏛️ **Artemius AI обрабатывает:** \"{prompt}\"\n\n💡 Получил ваш запрос! В полной версии использую DeepSeek V3 для глубокого анализа и развернутых ответов на любые вопросы."
    except Exception as e:
        return f"❌ Artemius временно недоступен: {str(e)}"

async def generate_image(prompt: str, user_id: int) -> str:
    """Генерация изображений (заглушка)"""
    try:
        use_feature(user_id, 'images')
        return f"🎨 **Artemius создает изображение:** \"{prompt}\"\n\n⚡ В полной версии использую Stable Diffusion XL для создания качественных изображений по вашему описанию!"
    except Exception as e:
        return f"❌ Ошибка генерации: {str(e)}"

async def generate_music(prompt: str, user_id: int) -> str:
    """Генерация музыки (заглушка)"""
    try:
        use_feature(user_id, 'music')
        return f"🎵 **Artemius компонует музыку:** \"{prompt}\"\n\n🎼 В полной версии использую MusicGen для создания уникальных композиций в любом жанре!"
    except Exception as e:
        return f"❌ Ошибка создания музыки: {str(e)}"

async def generate_video(prompt: str, user_id: int) -> str:
    """Генерация видео (заглушка)"""
    try:
        use_feature(user_id, 'video')
        return f"""🎬 **Artemius Video Studio**

📝 **Создается видео:** {prompt}

⚡ **Параметры:**
• AI: Veo 3, Kling AI, Pika 2.2
• Качество: HD (720p-1080p)
• Длительность: 5-10 секунд

🔄 **Статус:** Генерация...
⏱️ **Время:** 2-5 минут

💡 В полной версии интегрированы реальные video API!"""
    except Exception as e:
        return f"❌ Ошибка видео: {str(e)}"

async def analyze_document(user_id: int) -> str:
    """Анализ документов (заглушка)"""
    try:
        use_feature(user_id, 'documents')
        return f"""📄 **Artemius Document Analysis**

✅ Документ успешно обработан!

🔍 **Использованы технологии:**
• Microsoft TrOCR для распознавания текста
• Нейросетевая обработка изображения
• Многоязычный анализ

💡 В полной версии: точное распознавание текста с любых документов, переводы, ответы на вопросы по содержанию!"""
    except Exception as e:
        return f"❌ Ошибка OCR: {str(e)}"

# Обработчики состояний
@dp.message(StateFilter(BotStates.waiting_for_text))
async def process_chat_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not await check_limit(user_id, 'chat'):
        await show_limit_exhausted(message, 'chat')
        return

    await bot.send_chat_action(message.chat.id, "typing")
    processing_msg = await message.answer("🏛️ Artemius думает...")

    response = await chat_with_ai(message.text, user_id)
    await processing_msg.delete()
    await message.answer(response, parse_mode="Markdown")

@dp.message(StateFilter(BotStates.waiting_for_image_prompt))
async def process_image_generation(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not await check_limit(user_id, 'images'):
        await show_limit_exhausted(message, 'images')
        return

    await bot.send_chat_action(message.chat.id, "upload_photo")
    processing_msg = await message.answer("🎨 Artemius создаёт...")

    response = await generate_image(message.text, user_id)
    await processing_msg.delete()
    await message.answer(response, parse_mode="Markdown")

@dp.message(StateFilter(BotStates.waiting_for_music_prompt))
async def process_music_generation(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not await check_limit(user_id, 'music'):
        await show_limit_exhausted(message, 'music')
        return

    await bot.send_chat_action(message.chat.id, "upload_document")
    processing_msg = await message.answer("🎵 Artemius компонует...")

    response = await generate_music(message.text, user_id)
    await processing_msg.delete()
    await message.answer(response, parse_mode="Markdown")

@dp.message(StateFilter(BotStates.waiting_for_video_prompt))
async def process_video_generation(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not await check_limit(user_id, 'video'):
        await show_limit_exhausted(message, 'video')
        return

    await bot.send_chat_action(message.chat.id, "upload_video")
    processing_msg = await message.answer("🎬 Artemius создаёт видео...")

    response = await generate_video(message.text, user_id)
    await processing_msg.delete()
    await message.answer(response, parse_mode="Markdown")

@dp.message(StateFilter(BotStates.waiting_for_document), F.photo)
async def process_document_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not await check_limit(user_id, 'documents'):
        await show_limit_exhausted(message, 'documents')
        return

    await bot.send_chat_action(message.chat.id, "typing")
    processing_msg = await message.answer("📄 Artemius сканирует...")

    response = await analyze_document(user_id)
    await processing_msg.delete()
    await message.answer(response, parse_mode="Markdown")

@dp.message()
async def handle_unknown_message(message: types.Message):
    """Обработка неизвестных сообщений"""
    user_id = message.from_user.id
    await message.answer(
        f"🤔 **Artemius не понял команду**\n\n"
        f"💡 Используйте кнопки меню для навигации",
        reply_markup=await get_main_menu(user_id),
        parse_mode="Markdown"
    )

# Запуск Artemius
async def main():
    """Запуск Artemius с улучшенной системой подписок"""
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🏛️ ARTEMIUS AI BOT - ЗАПУЩЕН С КАНАЛАМИ @kanal1kkal и @kanal2kkal!")
        logger.info(f"📢 VIP требует подписки на: {[ch['id'] for ch in REQUIRED_CHANNELS]}")

        print("🏛️ ===== ARTEMIUS AI - ГОТОВ К РАБОТЕ =====")
        print(f"📢 VIP каналы: @kanal1kkal и @kanal2kkal")
        print(f"🔒 Базовые лимиты: {FREE_LIMITS}")
        print(f"⭐ VIP лимиты: {VIP_LIMITS}")
        print("💡 Система готова к привлечению пользователей!")

        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Artemius AI Bot остановлен")
