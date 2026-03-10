import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, date, timedelta, timezone
import json
import os
import shutil
import asyncio
import glob

from pydrive2.auth import ServiceAccountCredentials
from pydrive2.drive import GoogleDrive

# ================= ENV =================

TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

if not TOKEN:
    raise ValueError("DISCORD_TOKEN not found in Railway Variables")

DATA_FILE = "members.json"
BACKUP_FILE = "members_backup.json"

FOLDER_ID = "1sPQUdBZce1Os4oRPkDWFqsgzgkp95cha"

LOGO = "https://cdn.discordapp.com/attachments/1468621028598087843/1481027347124719707/member.png"

ROLE_PACKAGES = {
    "VIP": {"price": 200, "days": 30},
    "Supreme": {"price": 300, "days": 30}
}

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================= JSON =================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):

    tmp = "members.tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    os.replace(tmp, DATA_FILE)
    shutil.copy(DATA_FILE, BACKUP_FILE)

DATA = load_data()

# ================= GOOGLE DRIVE =================

def upload_to_drive(file_name):

    try:

        scope = ["https://www.googleapis.com/auth/drive"]

        creds = ServiceAccountCredentials.from_json_keyfile_name(
            "drive_key.json", scope
        )

        drive = GoogleDrive(creds)

        file_drive = drive.CreateFile({
            "title": file_name,
            "parents": [{"id": FOLDER_ID}]
        })

        file_drive.SetContentFile(file_name)
        file_drive.Upload()

        print("Uploaded to Google Drive:", file_name)

    except Exception as e:
        print("Drive upload error:", e)

# ================= QUEUE =================

queue = asyncio.Queue()

@tasks.loop(seconds=1)
async def queue_worker():

    if queue.empty():
        await asyncio.sleep(1)
        return

    task = await queue.get()

    if task["type"] == "add_role":
        try:
            await task["member"].add_roles(task["role"])
        except:
            pass

    if task["type"] == "remove_role":
        try:
            await task["member"].remove_roles(task["role"])
        except:
            pass

# ================= TIME =================

def parse_date(text):
    return datetime.strptime(text, "%d/%m/%y").date()

def calc_expire(start):
    return start + timedelta(days=29)

# ================= EMBED =================

def build_embed(member, info):

    role = member.guild.get_role(info["role_id"])

    start = date.fromisoformat(info["start_date"])
    expire = date.fromisoformat(info["expire_date"])

    embed = discord.Embed(
        title="👑 สถานะสมาชิก",
        color=discord.Color.gold()
    )

    embed.set_thumbnail(url=LOGO)

    embed.add_field(name="👤 ผู้รับ Role", value=member.mention, inline=False)

    embed.add_field(name="🎭 Role", value=role.mention if role else "-", inline=False)

    embed.add_field(name="📅 วันที่สมัคร", value=start.strftime("%d/%m/%Y"), inline=True)

    embed.add_field(name="📅 วันหมดอายุ", value=expire.strftime("%d/%m/%Y"), inline=True)

    embed.set_footer(text="Member System")

    return embed

# ================= DM =================

async def dm_user(member, text):
    if not member:
        return
    try:
        await member.send(text)
    except:
        pass

async def dm_admin(text):
    admin = bot.get_user(ADMIN_ID)
    if admin:
        try:
            await admin.send(text)
        except:
            pass

# ================= BUTTON =================

class CancelView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="❌ ยกเลิก Role", style=discord.ButtonStyle.red)

    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("❌ admin only", ephemeral=True)
            return

        message_id = interaction.message.id

        member_id = None
        info = None

        for uid, data in DATA.items():
            if data.get("message_id") == message_id:
                member_id = uid
                info = data
                break

        if not member_id:
            await interaction.response.send_message("❌ ไม่พบข้อมูล", ephemeral=True)
            return

        member = interaction.guild.get_member(int(member_id))
        role = interaction.guild.get_role(info["role_id"])

        if not member or not role:
            await interaction.response.send_message("❌ ไม่พบ member หรือ role")
            return

        await queue.put({
            "type": "remove_role",
            "member": member,
            "role": role
        })

        await dm_user(member, "⛔ Role สมาชิกของคุณถูกยกเลิกแล้ว")
        await dm_admin(f"❌ ยกเลิก Role ของ {member}")

        del DATA[member_id]
        save_data(DATA)

        await interaction.response.send_message("✅ ยกเลิก Role แล้ว")

# ================= SET ROLE =================

@bot.tree.command(name="setrole")

async def setrole(interaction: discord.Interaction, member: discord.Member, role: discord.Role, start_date: str):

    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("❌ admin only", ephemeral=True)
        return

    start = parse_date(start_date)
    expire = calc_expire(start)

    await queue.put({
        "type": "add_role",
        "member": member,
        "role": role
    })

    info = {
        "role_id": role.id,
        "start_date": start.isoformat(),
        "expire_date": expire.isoformat(),
        "warned": False
    }

    embed = build_embed(member, info)

    await interaction.response.send_message(embed=embed, view=CancelView())

    msg = await interaction.original_response()

    info["channel_id"] = msg.channel.id
    info["message_id"] = msg.id

    DATA[str(member.id)] = info
    save_data(DATA)

# ================= EXPIRE CHECK =================

@tasks.loop(minutes=10)

async def check_expire():

    now = datetime.now(timezone.utc)

    if not bot.guilds:
        return

    guild = bot.guilds[0]

    changed = False

    for uid, info in list(DATA.items()):

        member = guild.get_member(int(uid))
        role = guild.get_role(info["role_id"])

        if not member or not role:
            continue

        expire = date.fromisoformat(info["expire_date"])
        expire_dt = datetime.combine(expire, datetime.max.time(), tzinfo=timezone.utc)

        remain = expire_dt - now

        if remain.days == 3 and not info["warned"]:

            await dm_user(member, "⚠ สมาชิกจะหมดอายุในอีก 3 วัน")
            info["warned"] = True
            changed = True

        if now >= expire_dt:

            await queue.put({
                "type": "remove_role",
                "member": member,
                "role": role
            })

            await dm_user(member, "⛔ สมาชิกของคุณหมดอายุแล้ว")

            del DATA[uid]
            changed = True

    if changed:
        save_data(DATA)

# ================= BACKUP =================

@tasks.loop(hours=6)

async def auto_backup():

    if not os.path.exists(DATA_FILE):
        return

    now = datetime.now().strftime("%Y-%m-%d_%H-%M")

    name = f"backup_members_{now}.json"

    shutil.copy(DATA_FILE, name)

    upload_to_drive(name)

    print("Backup created:", name)

# ================= CLEAN BACKUP =================

@tasks.loop(hours=12)

async def clean_backup():

    files = sorted(glob.glob("backup_members_*.json"))

    if len(files) <= 10:
        return

    old = files[:-10]

    for f in old:
        os.remove(f)

    print("Old backups cleaned")

# ================= READY =================

@bot.event
async def on_ready():

    await bot.tree.sync()

    bot.add_view(CancelView())

    queue_worker.start()
    check_expire.start()
    auto_backup.start()
    clean_backup.start()

    print("BOT ONLINE")

bot.run(TOKEN)