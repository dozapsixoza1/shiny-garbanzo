import logging
import asyncio
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message

# --- КОНФИГ ---
API_TOKEN = '8751530782:AAEYl88Tw5aKRgA0pbk5TLdkD4Ea_iik-HM'
OWNER_ID = 7950038145  # ТВОЙ Telegram ID (главный админ)
MATCH_SIZE = 4  # Для теста поставим 4 (например, формат 2 на 2)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- ИМИТАЦИЯ БАЗЫ ДАННЫХ ---
users = {}    # {tg_id: {'game_id': str, 'nickname': str, 'elo': 1000}}
admins = {OWNER_ID}  # Сет с ID админов (владелец админ по умолчанию)
queue = []    # Очередь tg_id
matches = {}  # {match_id: {'players': [], 'status': 'waiting/playing'}}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def is_admin(user_id):
    return user_id in admins

# ==========================================
#              КОМАНДЫ ИГРОКОВ
# ==========================================

@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "🔴 **Lethal Strike: Standoff 2** 🔴\n\n"
        "1. Зарегистрируйся: `/reg [Игровой_ID] [Ник]`\n"
        "2. Начни поиск: `/play`\n\n"
        "Твоя цель — поднять свой Elo!"
    )

@dp.message(Command("reg"))
async def reg_cmd(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        return await message.answer("❌ Ошибка! Пиши так: `/reg 12345678 Snayper`")
    
    game_id, nickname = args[1], args[2]
    users[message.from_user.id] = {
        'game_id': game_id,
        'nickname': nickname,
        'elo': 1000
    }
    await message.answer(f"✅ Регистрация успешна!\nID: {game_id}\nНик: {nickname}\nТвой стартовый Elo: 1000")

@dp.message(Command("play"))
async def play_cmd(message: Message):
    user_id = message.from_user.id
    if user_id not in users:
        return await message.answer("❌ Сначала зарегистрируйся через `/reg`")
    
    if user_id in queue:
        return await message.answer("⏳ Ты уже в очереди.")

    queue.append(user_id)
    await message.answer(f"🔎 Поиск матча... (В очереди: {len(queue)}/{MATCH_SIZE})")

    # Если набралось нужное количество людей
    if len(queue) >= MATCH_SIZE:
        match_id = random.randint(1000, 9999)
        players = [queue.pop(0) for _ in range(MATCH_SIZE)]
        matches[match_id] = {'players': players, 'status': 'waiting'}

        # Формируем список игроков для сообщения
        player_list = "\n".join([f"• {users[p]['nickname']} (TG: {p})" for p in players])
        
        for p_id in players:
            await bot.send_message(p_id, f"🎮 **Матч #{match_id} найден!**\n\nИгроки:\n{player_list}\n\nОжидайте лобби от админа.")
        
        # Уведомляем админов, чтобы создали лобби
        for adm in admins:
            try:
                await bot.send_message(adm, f"⚡ **Матч #{match_id} собран!**\nСостав:\n{player_list}\n\nКинь лобби командой: `/lobby {match_id} [инфо]`")
            except:
                pass # Если админ заблокировал бота

# ==========================================
#              КОМАНДЫ АДМИНОВ
# ==========================================

@dp.message(Command("addadmin"))
async def add_admin(message: Message):
    if message.from_user.id != OWNER_ID: return
    args = message.text.split()
    if len(args) < 2: return await message.answer("Формат: `/addadmin [TG_ID]`")
    
    try:
        new_admin = int(args[1])
        admins.add(new_admin)
        await message.answer(f"✅ Пользователь {new_admin} назначен админом.")
    except ValueError:
        await message.answer("ID должен быть числом.")

@dp.message(Command("deladmin"))
async def del_admin(message: Message):
    if message.from_user.id != OWNER_ID: return
    args = message.text.split()
    if len(args) < 2: return await message.answer("Формат: `/deladmin [TG_ID]`")
    
    try:
        old_admin = int(args[1])
        if old_admin == OWNER_ID:
            return await message.answer("❌ Нельзя удалить самого себя (Владельца).")
        if old_admin in admins:
            admins.remove(old_admin)
            await message.answer(f"❌ Пользователь {old_admin} лишен прав админа.")
        else:
            await message.answer("Этот пользователь не является админом.")
    except ValueError:
        await message.answer("ID должен быть числом.")

@dp.message(Command("lobby"))
async def lobby_cmd(message: Message):
    if not is_admin(message.from_user.id): return
    
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        return await message.answer("Формат: `/lobby [ID_матча] [Инфо (ID лобби и пароль)]`")
    
    try:
        m_id = int(args[1])
        info = args[2]
    except ValueError:
        return await message.answer("ID матча должен быть числом.")

    if m_id not in matches:
        return await message.answer("❌ Матч не найден.")

    matches[m_id]['status'] = 'playing'
    for p_id in matches[m_id]['players']:
        await bot.send_message(p_id, f"🔗 **ДАННЫЕ ЛОББИ (Матч #{m_id})**\n\n{info}\n\nЗаходите в игру!")
    
    await message.answer(f"✅ Данные лобби отправлены всем игрокам матча #{m_id}.")

@dp.message(Command("setwin"))
async def set_win(message: Message):
    if not is_admin(message.from_user.id): return
    
    args = message.text.split()
    if len(args) < 3:
        return await message.answer("Формат: `/setwin [ID_матча] [ID1,ID2,ID3...]`\nПример: `/setwin 1234 111111,222222`")
    
    try:
        m_id = int(args[1])
        # Разделяем введенные ID по запятой, очищаем от пробелов и переводим в числа
        win_ids = [int(x.strip()) for x in args[2].split(',')]
    except ValueError:
        return await message.answer("❌ Ошибка в формате. Проверь, что ID матча и ID игроков — это числа (через запятую).")
    
    if m_id not in matches:
        return await message.answer("❌ Матч не найден.")

    players = matches[m_id]['players']
    
    for p_id in players:
        if p_id in win_ids:
            users[p_id]['elo'] += 25
            try:
                await bot.send_message(p_id, f"🏆 **ПОБЕДА!** Твоя команда выиграла матч #{m_id}. Тебе начислено +25 Elo. (Всего: {users[p_id]['elo']})")
            except: pass
        else:
            users[p_id]['elo'] -= 25
            try:
                await bot.send_message(p_id, f"📉 **ПОРАЖЕНИЕ.** Твоя команда проиграла матч #{m_id}. Списано -25 Elo. (Всего: {users[p_id]['elo']})")
            except: pass
    
    del matches[m_id]
    await message.answer(f"🏁 Результат матча #{m_id} записан.\nПобедители (получили +25): {win_ids}")

async def main():
    print("Бот Lethal Strike запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
