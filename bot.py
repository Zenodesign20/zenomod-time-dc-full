import discord
from discord.ext import commands, tasks
import json
import datetime
import asyncio
import os

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
LOGO_URL = os.getenv("LOGO_URL", "")

if not TOKEN:
    print("❌ TOKEN not found in environment variables")
    exit()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

queue = asyncio.Queue()

# ---------- JSON ----------
def load_members():
    try:
        with open("members.json","r") as f:
            return json.load(f)
    except:
        return {}

def save_members(data):
    with open("members.json","w") as f:
        json.dump(data,f,indent=4)

def backup_members():
    data = load_members()
    with open("members_backup.json","w") as f:
        json.dump(data,f,indent=4)

# ---------- EMBED ----------
def member_embed(member,role,start,expire,package):
    embed = discord.Embed(
        title="📌 สถานะสมาชิก",
        color=discord.Color.green()
    )

    embed.add_field(name="👤 ผู้รับ Role",value=member.mention,inline=False)
    embed.add_field(name="🎭 Role",value=role.mention,inline=False)
    embed.add_field(name="📅 วันที่สมัคร",value=start,inline=True)
    embed.add_field(name="💎 แพ็กเกจ",value=package,inline=False)
    embed.add_field(name="📅 วันหมดอายุ",value=expire,inline=True)

    if LOGO_URL:
        embed.set_thumbnail(url=LOGO_URL)

    embed.set_footer(text="ZenoMOD Member System")
    return embed

def expired_embed(user_id):
    embed = discord.Embed(
        title="📌 สถานะสมาชิก",
        description=f"""สมาชิก: <@{user_id}>

สถานะ: Member หมดอายุ
หมายเหตุ: ติดต่อสมัครสมาชิกที่ห้องติดต่อ""",
        color=discord.Color.red()
    )

    if LOGO_URL:
        embed.set_thumbnail(url=LOGO_URL)

    return embed

def cancel_embed(member):
    embed = discord.Embed(
        title="📌 สถานะสมาชิก",
        description=f"""สมาชิก: {member.mention}

สถานะ: ยกเลิกแล้ว""",
        color=discord.Color.red()
    )

    if LOGO_URL:
        embed.set_thumbnail(url=LOGO_URL)

    return embed

# ---------- BUTTON ----------
class CancelView(discord.ui.View):

    def __init__(self,user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="ยกเลิก Role",style=discord.ButtonStyle.red)
    async def cancel(self,interaction:discord.Interaction,button:discord.ui.Button):

        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("ไม่มีสิทธิ์",ephemeral=True)
            return

        data = load_members()
        if str(self.user_id) not in data:
            await interaction.response.send_message("ไม่พบข้อมูล",ephemeral=True)
            return

        info = data[str(self.user_id)]
        guild = interaction.guild
        member = guild.get_member(self.user_id)
        role = guild.get_role(info["role_id"])

        if member and role:
            try:
                await member.remove_roles(role)
            except:
                pass

        embed = cancel_embed(member)
        await interaction.message.edit(embed=embed,view=None)

        try:
            await member.send("Role ของคุณถูกยกเลิกแล้ว")
        except:
            pass

        del data[str(self.user_id)]
        save_members(data)

        await interaction.response.send_message("ยกเลิกสำเร็จ",ephemeral=True)

# ---------- COMMAND ----------
@bot.tree.command(name="setrole", description="เพิ่มสมาชิก")
async def setrole(interaction:discord.Interaction,user:discord.Member,role:discord.Role,days:int,price:str):

    start = datetime.datetime.now()
    expire = start + datetime.timedelta(days=days)

    start_str = start.strftime("%d/%m/%Y")
    expire_str = expire.strftime("%d/%m/%Y")

    await user.add_roles(role)

    embed = member_embed(
        user,
        role,
        start_str,
        expire_str,
        f"{role.name} | ราคา {price} | {days} วัน"
    )

    view = CancelView(user.id)
    msg = await interaction.channel.send(embed=embed,view=view)

    data = load_members()
    data[str(user.id)] = {
        "guild_id":interaction.guild.id,
        "role_id":role.id,
        "start_date":start_str,
        "expire_date":expire_str,
        "channel_id":msg.channel.id,
        "message_id":msg.id
    }

    save_members(data)

    try:
        await user.send("คุณได้รับ Role Member แล้ว")
    except:
        pass

    await interaction.response.send_message("สมัครสมาชิกสำเร็จ",ephemeral=True)

# ---------- EXPIRE CHECK ----------
@tasks.loop(minutes=10)
async def check_expire():

    data = load_members()
    now = datetime.datetime.now()

    for user_id,info in list(data.items()):
        try:
            guild = bot.get_guild(info["guild_id"])
            member = guild.get_member(int(user_id))
            role = guild.get_role(info["role_id"])

            expire = datetime.datetime.strptime(info["expire_date"],"%d/%m/%Y")

            if now >= expire:

                if member and role:
                    try:
                        await member.remove_roles(role)
                    except:
                        pass

                channel = bot.get_channel(info["channel_id"])

                try:
                    message = await channel.fetch_message(info["message_id"])
                    embed = expired_embed(user_id)
                    await message.edit(embed=embed,view=None)
                except:
                    pass

                try:
                    await member.send("สมาชิกของคุณหมดอายุแล้ว")
                except:
                    pass

                del data[user_id]
                save_members(data)

        except:
            continue

# ---------- BACKUP ----------
@tasks.loop(hours=4)
async def auto_backup():
    backup_members()

# ---------- READY ----------
@bot.event
async def on_ready():

    print("ZenoMOD Member Bot Online")

    check_expire.start()
    auto_backup.start()

    try:
        synced = await bot.tree.sync()
        print(f"Slash synced {len(synced)}")
    except:
        pass

bot.run(TOKEN)