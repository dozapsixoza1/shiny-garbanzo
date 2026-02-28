import logging
import asyncio
import random
import json
import time
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
#              НАСТРОЙКИ
# ==========================================
API_TOKEN = '8751530782:AAEYl88Tw5aKRgA0pbk5TLdkD4Ea_iik-HM'
OWNER_ID = 12345678  # Твой Telegram ID
MATCH_SIZE = 4  # Количество игроков для матча (10 для 5х5)
DB_NAME = "lethal_ultra.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Состояния
class RegState(StatesGroup):
    game_id, nickname, rank, mmr = State(), State(), State(), State()

class ReportState(StatesGroup):
    text = State()

# ==========================================
#              БАЗА ДАННЫХ
# ==========================================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY, game_id TEXT, nickname TEXT, 
            rank TEXT, mmr INTEGER, elo INTEGER DEFAULT 1000, 
            wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, banned_until INTEGER DEFAULT 0)""")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (tg_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS matches (match_id INTEGER PRIMARY KEY, players TEXT, team1 TEXT, team2 TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS subs (channel_id INTEGER PRIMARY KEY, url TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        
        await db.execute("INSERT OR IGNORE INTO admins (tg_id) VALUES (?)", (OWNER_ID,))
        await db.commit()

async def get_user(tg_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)) as cursor: return await cursor.fetchone()

async def is_admin(tg_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM admins WHERE tg_id = ?", (tg_id,)) as cursor: return await cursor.fetchone() is not None

# ==========================================
#           ПРОВЕРКА ПОДПИСОК
# ==========================================
async def check_all_subs(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id, url FROM subs") as cursor:
            channels = await cursor.fetchall()
    
    unsubbed = []
    for c_id, url in channels:
        try:
            m = await bot.get_chat_member(c_id, user_id)
            if m.status not in ["member", "administrator", "creator"]:
                unsubbed.append(url)
        except:
            continue # Если бота выкинули из канала, пропускаем
    return unsubbed

# ==========================================
#                КЛАВИАТУРЫ
# ==========================================
def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Найти матч", callback_data="join_q")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"), InlineKeyboardButton(text="🏆 ТОП", callback_data="top")],
        [InlineKeyboardButton(text="⚠️ Репорт", callback_data="make_report"), InlineKeyboardButton(text="❌ Выйти", callback_data="leave_q")]
    ])

# ==========================================
#                ЛОГИКА ИГРЫ
# ==========================================
queue = []

@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    # Проверка бана
    user = await get_user(message.from_user.id)
    if user and user[8] > time.time():
        return await message.answer(f"🚫 Ты забанен до {time.ctime(user[8])}")

    # Проверка подписок
    unsubbed = await check_all_subs(message.from_user.id)
    if unsubbed:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Подписаться", url=link)] for link in unsubbed])
        kb.inline_keyboard.append([InlineKeyboardButton(text="✅ Проверить", callback_data="check_subs")])
        return await message.answer("⚠️ Для доступа к боту подпишись на каналы:", reply_markup=kb)

    if not user:
        await message.answer("🔴 **Lethal Strike**\nВведите ваш **ID Standoff 2**:")
        await state.set_state(RegState.game_id)
    else:
        await message.answer(f"👋 С возвращением, {user[2]}!", reply_markup=main_kb())

@dp.callback_query(F.data == "check_subs")
async def check_subs_cb(call: CallbackQuery, state: FSMContext):
    await call.message.delete()
    await start(call.message, state)

# --- РЕГИСТРАЦИЯ ---
@dp.message(RegState.game_id)
async def reg1(message: Message, state: FSMContext):
    await state.update_data(game_id=message.text)
    await message.answer("Твой ник:")
    await state.set_state(RegState.nickname)

@dp.message(RegState.nickname)
async def reg2(message: Message, state: FSMContext):
    await state.update_data(nickname=message.text)
    ranks = ["Бронза", "Сильвер", "Голд", "Феникс", "Рейнджер", "Мастер", "Элита", "Легенда"]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=r, callback_data=f"r_{r}")] for r in ranks])
    await message.answer("Твое звание в ММ:", reply_markup=kb)
    await state.set_state(RegState.rank)

@dp.callback_query(F.data.startswith("r_"))
async def reg3(call: CallbackQuery, state: FSMContext):
    await state.update_data(rank=call.data.split("_")[1])
    await call.message.answer("Введи количество MMR цифрами:")
    await state.set_state(RegState.mmr)

@dp.message(RegState.mmr)
async def reg4(message: Message, state: FSMContext):
    if not message.text.isdigit(): return
    d = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO users (tg_id, game_id, nickname, rank, mmr) VALUES (?,?,?,?,?)",
                         (message.from_user.id, d['game_id'], d['nickname'], d['rank'], int(message.text)))
        await db.commit()
    await state.clear()
    await message.answer("✅ Регистрация завершена!", reply_markup=main_kb())

# --- МАТЧМЕЙКИНГ ---
@dp.callback_query(F.data == "join_q")
async def join_q(call: CallbackQuery):
    if call.from_user.id in queue: return await call.answer("Уже в поиске")
    queue.append(call.from_user.id)
    await call.message.edit_text(f"🔎 Поиск... [{len(queue)}/{MATCH_SIZE}]", reply_markup=main_kb())

    if len(queue) >= MATCH_SIZE:
        ids = [queue.pop(0) for _ in range(MATCH_SIZE)]
        players = []
        async with aiosqlite.connect(DB_NAME) as db:
            for pid in ids:
                async with db.execute("SELECT tg_id, nickname, mmr, elo FROM users WHERE tg_id=?", (pid,)) as cur:
                    r = await cur.fetchone()
                    players.append({'id': r[0], 'nick': r[1], 'mmr': r[2], 'elo': r[3]})

        players.sort(key=lambda x: (x['mmr'] + x['elo']), reverse=True)
        t1, t2 = [], []
        for i, p in enumerate(players):
            if i % 2 == 0: t1.append(p)
            else: t2.append(p)

        m_id = random.randint(1000, 9999)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO matches (match_id, players, team1, team2) VALUES (?,?,?,?)", 
                             (m_id, json.dumps(ids), json.dumps(t1), json.dumps(t2)))
            await db.commit()

        msg = f"🎮 **МАТЧ #{m_id}**\n\n🔵 **Team CT:**\n" + "\n".join([f"• {p['nick']} (`{p['id']}`)" for p in t1])
        msg += "\n\n🔴 **Team T:**\n" + "\n".join([f"• {p['nick']} (`{p['id']}`)" for p in t2])
        for pid in ids:
            try: await bot.send_message(pid, msg)
            except: pass

# ==========================================
#                АДМИНКА
# ==========================================

@dp.message(Command("addsub"))
async def add_sub(message: Message):
    if not await is_admin(message.from_user.id): return
    args = message.text.split() # /addsub -100... https://t.me...
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO subs (channel_id, url) VALUES (?,?)", (int(args[1]), args[2]))
        await db.commit()
    await message.answer("✅ Канал добавлен в обязательные подписки.")

@dp.message(Command("delsub"))
async def del_sub(message: Message):
    if not await is_admin(message.from_user.id): return
    args = message.text.split()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM subs WHERE channel_id=?", (int(args[1]),))
        await db.commit()
    await message.answer("❌ Канал удален из подписок.")

@dp.message(Command("setlog"))
async def set_log(message: Message):
    if not await is_admin(message.from_user.id): return
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", ("log_channel", message.text.split()[1]))
        await db.commit()
    await message.answer("📺 Канал результатов установлен.")

@dp.message(Command("setwin"))
async def set_win(message: Message):
    if not await is_admin(message.from_user.id): return
    args = message.text.split()
    m_id, wins = int(args[1]), [int(x) for x in args[2].split(',')]
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT players, team1, team2 FROM matches WHERE match_id=?", (m_id,)) as cur:
            row = await cur.fetchone()
            all_p, t1, t2 = json.loads(row[0]), json.loads(row[1]), json.loads(row[2])
        
        winners_names, losers_names = [], []
        for pid in all_p:
            async with db.execute("SELECT nickname FROM users WHERE tg_id=?", (pid,)) as cur:
                nick = (await cur.fetchone())[0]
            if pid in wins:
                await db.execute("UPDATE users SET elo=elo+25, wins=wins+1 WHERE tg_id=?", (pid,))
                winners_names.append(nick)
                try: await bot.send_message(pid, "🏆 Победа! +25 Elo.")
                except: pass
            else:
                await db.execute("UPDATE users SET elo=elo-25, losses=losses+1 WHERE tg_id=?", (pid,))
                losers_names.append(nick)
                try: await bot.send_message(pid, "📉 Поражение. -25 Elo.")
                except: pass
        
        # Пост в канал результатов
        async with db.execute("SELECT value FROM settings WHERE key='log_channel'") as cur:
            log_res = await cur.fetchone()
            if log_res:
                log_msg = f"🏁 **РЕЗУЛЬТАТЫ МАТЧА #{m_id}**\n\n" \
                          f"🏆 **Победители (+25 Elo):**\n{', '.join(winners_names)}\n\n" \
                          f"💀 **Проигравшие (-25 Elo):**\n{', '.join(losers_names)}"
                await bot.send_message(log_res[0], log_msg)

        await db.execute("DELETE FROM matches WHERE match_id=?", (m_id,))
        await db.commit()
    await message.answer(f"✅ Матч #{m_id} завершен.")

@dp.message(Command("lobby"))
async def send_lobby(message: Message):
    if not await is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=2)
    m_id, info = int(args[1]), args[2]
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT players FROM matches WHERE match_id=?", (m_id,)) as cur:
            row = await cur.fetchone()
            if row:
                for pid in json.loads(row[0]):
                    await bot.send_message(pid, f"🔗 **ЛОББИ #{m_id}:**\n`{info}`")
    await message.answer("✅ Данные отправлены.")

@dp.message(Command("ban"))
async def ban(message: Message):
    if not await is_admin(message.from_user.id): return
    args = message.text.split()
    target, mins = int(args[1]), int(args[2])
    end = time.time() + (mins * 60)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET banned_until=? WHERE tg_id=?", (end, target))
        await db.commit()
    await message.answer(f"🚫 Игрок {target} забанен.")

# ==========================================
#              ЗАПУСК
# ==========================================
async def main():
    await init_db()
    print("🚀 Lethal Strike Ultra запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
