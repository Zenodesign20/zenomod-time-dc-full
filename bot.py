import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import shutil
from datetime import datetime, timedelta, date

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

DATA_FILE = "members.json"
BACKUP_FILE = "members_backup.json"

# Google Drive
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- JSON ----------------

def load_data():

    if not os.path.exists(DATA_FILE):

        if os.path.exists(BACKUP_FILE):
            shutil.copy(BACKUP_FILE, DATA_FILE)
        else:
            return {}

    with open(DATA_FILE,"r",encoding="utf-8") as f:
        return json.load(f)


def save_data(data):

    with open(DATA_FILE,"w",encoding="utf-8") as f:
        json.dump(data,f,indent=4)

    shutil.copy(DATA_FILE,BACKUP_FILE)

# ---------------- TIME ----------------

def parse_date(text):
    return datetime.strptime(text,"%d/%m/%y").date()

def calc_expire(start):
    return start + timedelta(days=29)

# ---------------- EMBED ----------------

def build_embed(member,role,start,expire):

    embed = discord.Embed(
        title="👑 สถานะสมาชิก",
        color=discord.Color.gold()
    )

    embed.add_field(name="👤 ผู้รับ Role",value=member.mention,inline=False)
    embed.add_field(name="🎭 Role",value=role.mention,inline=False)
    embed.add_field(name="📅 วันที่สมัคร",value=start.strftime("%d/%m/%Y"))
    embed.add_field(name="📅 วันหมดอายุ",value=expire.strftime("%d/%m/%Y"))

    return embed

def build_expired_embed(member):

    embed = discord.Embed(
        title="🔒 สถานะสมาชิก",
        description=
        f"""ชื่อ : {member.mention}
สถานะ : Member ของท่านหมดอายุ
หมายเหตุ : ติดต่อสมัครสมาชิกได้ที่ห้องติดต่อ

-------------------------------------
Member Shop :
Vip Member - 200.- / 30วัน
Supreme Member - 200.- / 30วัน
""",
        color=discord.Color.dark_grey()
    )

    return embed

# ---------------- GOOGLE DRIVE ----------------

def upload_drive():

    try:

        SCOPES=['https://www.googleapis.com/auth/drive']

        creds=service_account.Credentials.from_service_account_file(
            'drive_key.json',scopes=SCOPES
        )

        service=build('drive','v3',credentials=creds)

        file_metadata={
            'name':'members_backup.json',
            'parents':[DRIVE_FOLDER_ID]
        }

        media=MediaFileUpload(DATA_FILE,mimetype='application/json')

        service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

        print("Google Drive backup complete")

    except Exception as e:

        print("Drive backup error",e)

@tasks.loop(hours=4)
async def google_drive_backup():

    if os.path.exists(DATA_FILE):

        upload_drive()

# ---------------- BUTTON ----------------

class CancelRole(discord.ui.View):

    def __init__(self,member_id):
        super().__init__(timeout=None)
        self.member_id=member_id

    @discord.ui.button(label="❌ ยกเลิก Role",style=discord.ButtonStyle.red,custom_id="cancel_role")

    async def cancel(self,interaction:discord.Interaction,button:discord.ui.Button):

        if interaction.user.id!=ADMIN_ID:

            await interaction.response.send_message("admin only",ephemeral=True)
            return

        data=load_data()
        uid=str(self.member_id)

        if uid not in data:

            await interaction.response.send_message("ไม่มีข้อมูล",ephemeral=True)
            return

        info=data[uid]

        member=interaction.guild.get_member(int(uid))
        role=interaction.guild.get_role(info["role"])

        if member and role:

            await member.remove_roles(role)

        del data[uid]
        save_data(data)

        try:
            await member.send("❌ Role ของคุณถูกยกเลิกแล้ว")
        except:
            pass

        admin=bot.get_user(ADMIN_ID)

        if admin:
            await admin.send(f"❌ ยกเลิก Role ของ {member}")

        await interaction.response.send_message("ยกเลิกแล้ว")

# ---------------- COMMAND ----------------

@bot.tree.command(name="setrole")

async def setrole(interaction:discord.Interaction,user:discord.Member,role:discord.Role,start_date:str):

    if interaction.user.id!=ADMIN_ID:

        await interaction.response.send_message("admin only",ephemeral=True)
        return

    start=parse_date(start_date)
    expire=calc_expire(start)

    await user.add_roles(role)

    embed=build_embed(user,role,start,expire)

    view=CancelRole(user.id)

    await interaction.response.send_message(embed=embed,view=view)

    msg=await interaction.original_response()

    data=load_data()

    data[str(user.id)]={
        "role":role.id,
        "start":start.isoformat(),
        "expire":expire.isoformat(),
        "channel":msg.channel.id,
        "message":msg.id
    }

    save_data(data)

# ---------------- CHECK EXPIRE ----------------

@tasks.loop(minutes=30)

async def check_expire():

    data=load_data()

    guild=bot.guilds[0]

    now=datetime.utcnow().date()

    for uid,info in list(data.items()):

        expire=date.fromisoformat(info["expire"])

        if now>=expire:

            member=guild.get_member(int(uid))
            role=guild.get_role(info["role"])

            if member and role:

                await member.remove_roles(role)

            try:

                channel=bot.get_channel(info["channel"])
                msg=await channel.fetch_message(info["message"])

                embed=build_expired_embed(member)

                await msg.edit(embed=embed,view=None)

            except:
                pass

            try:
                await member.send("⛔ Member ของคุณหมดอายุแล้ว")
            except:
                pass

            admin=bot.get_user(ADMIN_ID)

            if admin:
                await admin.send(f"⛔ Member หมดอายุ {member}")

            del data[uid]

    save_data(data)

# ---------------- RECOVER EMBED ----------------

async def recover_embed():

    await bot.wait_until_ready()

    data=load_data()
    guild=bot.guilds[0]

    for uid,info in data.items():

        try:

            member=guild.get_member(int(uid))
            role=guild.get_role(info["role"])

            start=date.fromisoformat(info["start"])
            expire=date.fromisoformat(info["expire"])

            channel=bot.get_channel(info["channel"])
            msg=await channel.fetch_message(info["message"])

            embed=build_embed(member,role,start,expire)

            view=CancelRole(member.id)

            await msg.edit(embed=embed,view=view)

        except:
            pass

# ---------------- READY ----------------

@bot.event
async def on_ready():

    await bot.tree.sync()

    bot.add_view(CancelRole(None))

    check_expire.start()

    google_drive_backup.start()

    bot.loop.create_task(recover_embed())

    print("BOT ONLINE")

bot.run(TOKEN)