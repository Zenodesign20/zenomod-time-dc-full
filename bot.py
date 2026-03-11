import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, date, timedelta, timezone
import json
import os
import shutil
import asyncio

# ===== (ADD) Google Drive libs (optional) =====
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GDRIVE_AVAILABLE = True
except:
    GDRIVE_AVAILABLE = False
# ==============================================

TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

DATA_FILE = "members.json"
BACKUP_FILE = "members_backup.json"

ROLE_PACKAGES = {
    "VIP": {"price": 200, "days": 30},
    "Supreme": {"price": 300, "days": 30}
}

GIF_THUMBNAIL = "https://cdn.discordapp.com/attachments/1468621028598087843/1471249375706746890/Black_White_Minimalist_Animation_Logo_Video_1.gif"

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- API QUEUE ----------------

api_queue = asyncio.Queue()

async def api_worker():
    while True:
        func, args, kwargs = await api_queue.get()
        try:
            await func(*args, **kwargs)
        except Exception as e:
            print("API ERROR:", e)

        await asyncio.sleep(1)
        api_queue.task_done()

async def queue_api(func, *args, **kwargs):
    await api_queue.put((func, args, kwargs))

# ---------------- JSON SAFE ----------------

def load_data():
    if not os.path.exists(DATA_FILE):
        if os.path.exists(BACKUP_FILE):
            shutil.copy(BACKUP_FILE, DATA_FILE)
        else:
            return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        if os.path.exists(BACKUP_FILE):
            shutil.copy(BACKUP_FILE, DATA_FILE)
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    shutil.copy(DATA_FILE, BACKUP_FILE)

# ---------------- TIME ----------------

def parse_date(text):
    return datetime.strptime(text, "%d/%m/%y").date()

def calc_expire(start):
    return start + timedelta(days=29)

# ---------------- PACKAGE ----------------

def get_package(role):
    for key in ROLE_PACKAGES:
        if role.name.startswith(key):
            p = ROLE_PACKAGES[key]
            return key, p["price"], p["days"]

    return role.name, "-", "-"

# ---------------- EMBED ----------------

def build_embed(member, info):

    role = member.guild.get_role(info["role_id"])

    package, price, days = get_package(role)

    start = date.fromisoformat(info["start_date"])
    expire = date.fromisoformat(info["expire_date"])

    color = discord.Color.gold()

    if package == "Supreme":
        color = discord.Color.red()

    embed = discord.Embed(
        title="👑 สถานะสมาชิก",
        color=color
    )

    embed.set_thumbnail(url=GIF_THUMBNAIL)

    embed.add_field(name="👤 ผู้รับ Role", value=member.mention, inline=False)

    embed.add_field(name="🎭 Role", value=role.mention if role else "-", inline=False)

    embed.add_field(name="📅 วันที่สมัคร", value=start.strftime("%d/%m/%Y"), inline=True)

    embed.add_field(
        name="💎 แพ็กเกจ",
        value=f"{package} | ราคา {price} บาท | จำนวน {days} วัน",
        inline=False
    )

    embed.add_field(name="📅 วันหมดอายุ", value=expire.strftime("%d/%m/%Y"), inline=True)

    embed.set_footer(text="Zeno thanks for your support")

    return embed


# ===== (ADD) EMBED เมื่อหมดอายุ =====
def build_expired_embed(member, info):
    embed = discord.Embed(
        title="👑 สถานะสมาชิก",
        description=f"สมาชิก: {member.mention}\n\nสถานะ: Member หมดอายุ\nหมายเหตุ: ติดต่อสมัครสมาชิกที่ห้องติดต่อ",
        color=discord.Color.dark_grey()
    )
    embed.set_thumbnail(url=GIF_THUMBNAIL)
    embed.set_footer(text="Zeno thanks for your support")
    return embed
# ====================================


# ---------------- DM ----------------

async def dm_user(member, text):
    try:
        await queue_api(member.send, text)
    except:
        pass

async def dm_admin(text):
    admin = bot.get_user(ADMIN_ID)

    if admin:
        try:
            await queue_api(admin.send, text)
        except:
            pass

# ---------------- BUTTON ----------------

class CancelRoleButton(discord.ui.View):

    def __init__(self, member_id=None):
        super().__init__(timeout=None)
        self.member_id = member_id

    @discord.ui.button(label="❌ ยกเลิก Role", style=discord.ButtonStyle.red, custom_id="cancel_member_role")

    async def cancel_role(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("❌ admin only", ephemeral=True)
            return

        data = load_data()

        uid = self.member_id or interaction.message.embeds[0].fields[0].value.strip("<@>")

        if str(uid) not in data:
            await interaction.response.send_message("❌ ไม่มีข้อมูล", ephemeral=True)
            return

        info = data[str(uid)]

        member = interaction.guild.get_member(int(uid))
        role = interaction.guild.get_role(info["role_id"])

        if member and role:
            await queue_api(member.remove_roles, role)

        del data[str(uid)]
        save_data(data)

        # ===== (ADD) แจ้งเตือนตอนยกเลิก =====
        if member:
            await dm_user(member, "❌ Role ของคุณถูกยกเลิกแล้ว")
        await dm_admin(f"❌ ยกเลิก Role ของ {member}")
        # ====================================

        await interaction.response.send_message("✅ ยกเลิก Role แล้ว")

# ---------------- SET ROLE ----------------

@bot.tree.command(name="setrole", description="เพิ่มสมาชิก")

async def setrole(interaction: discord.Interaction, member: discord.Member, role: discord.Role, start_date: str):

    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("❌ admin only", ephemeral=True)
        return

    start = parse_date(start_date)
    expire = calc_expire(start)

    await queue_api(member.add_roles, role)

    info = {
        "role_id": role.id,
        "start_date": start.isoformat(),
        "expire_date": expire.isoformat(),
        "warned": False
    }

    embed = build_embed(member, info)

    view = CancelRoleButton(member.id)

    await interaction.response.send_message(embed=embed, view=view)

    msg = await interaction.original_response()

    info["channel_id"] = msg.channel.id
    info["message_id"] = msg.id

    data = load_data()

    data[str(member.id)] = info

    save_data(data)

    package, price, days = get_package(role)

    await dm_user(member,
        f"👑 คุณได้รับ Role สมาชิก\n\n"
        f"Member : {package}\n"
        f"ราคา : {price} บาท\n"
        f"จำนวน : {days} วัน"
    )

    await dm_admin(f"✅ เพิ่ม Role ให้ {member}")


# ---------------- AUTO CHECK ----------------

@tasks.loop(minutes=30)

async def check_expire():

    data = load_data()

    now = datetime.now(timezone.utc)

    if not bot.guilds:
        return

    guild = bot.guilds[0]

    changed = False

    for uid, info in list(data.items()):

        member = guild.get_member(int(uid))
        role = guild.get_role(info["role_id"])

        if not member or not role:
            continue

        expire = date.fromisoformat(info["expire_date"])

        expire_dt = datetime.combine(expire, datetime.max.time(), tzinfo=timezone.utc)

        remain = expire_dt - now

        if remain.days <= 3 and not info["warned"]:

            await dm_user(member, "⚠ สมาชิกจะหมดอายุในอีก 3 วัน")

            await dm_admin(f"⚠ {member} จะหมดอายุใน 3 วัน")

            info["warned"] = True

            changed = True

        if now >= expire_dt:

            await queue_api(member.remove_roles, role)

            await dm_user(member, "⛔ สมาชิกของคุณหมดอายุแล้ว")

            await dm_admin(f"⛔ หมดอายุ {member}")

            # ===== (ADD) เปลี่ยน embed เมื่อหมดอายุ =====
            try:
                channel = bot.get_channel(info["channel_id"])
                msg = await channel.fetch_message(info["message_id"])
                embed = build_expired_embed(member, info)
                await queue_api(msg.edit, embed=embed, view=None)
            except:
                pass
            # ============================================

            del data[uid]

            changed = True

    if changed:
        save_data(data)


# ===== (ADD) Sync Embed & Button หลัง restart =====
async def rebuild_embeds():

    await bot.wait_until_ready()

    data = load_data()

    if not bot.guilds:
        return

    guild = bot.guilds[0]

    for uid, info in data.items():

        try:
            channel = bot.get_channel(info["channel_id"])
            msg = await channel.fetch_message(info["message_id"])

            member = guild.get_member(int(uid))

            if not member:
                continue

            expire = date.fromisoformat(info["expire_date"])
            today = datetime.utcnow().date()

            if today > expire:
                embed = build_expired_embed(member, info)
                await msg.edit(embed=embed, view=None)
            else:
                embed = build_embed(member, info)
                view = CancelRoleButton(int(uid))
                await msg.edit(embed=embed, view=view)

        except Exception as e:
            print("REBUILD ERROR", e)
# ===================================================


# ===== (ADD) Google Drive Backup ทุก 4 ชม =====
@tasks.loop(hours=4)
async def gdrive_backup():

    if not GDRIVE_AVAILABLE:
        return

    if not os.path.exists(DATA_FILE):
        return

    try:
        creds = service_account.Credentials.from_service_account_file(
            "service_account.json",
            scopes=["https://www.googleapis.com/auth/drive.file"]
        )

        service = build("drive", "v3", credentials=creds)

        media = MediaFileUpload(DATA_FILE, mimetype="application/json")

        service.files().create(
            body={"name": f"members_backup_{int(datetime.utcnow().timestamp())}.json"},
            media_body=media
        ).execute()

        print("GDRIVE BACKUP DONE")

    except Exception as e:
        print("GDRIVE ERROR", e)
# =================================================


# ---------------- READY ----------------

@bot.event
async def on_ready():

    await bot.tree.sync()

    bot.loop.create_task(api_worker())

    bot.add_view(CancelRoleButton())

    check_expire.start()

    # ===== (ADD) ระบบเสริม =====
    bot.loop.create_task(rebuild_embeds())
    if GDRIVE_AVAILABLE:
        gdrive_backup.start()
    # ============================

    print("BOT ONLINE")

bot.run(TOKEN)