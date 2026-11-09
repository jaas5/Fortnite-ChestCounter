import re
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands

# ==========================================
# CONFIGURAÇÃO DO BOT DO SQUAD
# ==========================================
# Cole o Token do seu Bot criado no Discord Developer Portal aqui:
BOT_TOKEN = "COLE_O_TOKEN_DO_SEU_BOT_AQUI"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Probabilidades base dos itens (evento One Piece)
ODDS = {
    "token": 1.0 / 137500.0,       # Acesso à Loja do Pirata: 1 em 137.500
    "gold_set": 1.0 / 1562500.0,   # Conjunto Dourado: 1 em 1.562.500
    "vehicle": 1.0 / 7813.0,       # Veículo Semanal & Adesivo: 1 em 7.813
    "pickaxe": 1.0 / 568.0,        # Picareta/Mochila: 1 em 568
    "music": 1.0 / 391.0,          # Música Semanal: 1 em 391
    "loading": 1.0 / 272.0,        # Tela de Carregamento: 1 em 272
    "trinket": 1.0 / 127.0         # Bugiganga: 1 em 127
}

def calc_chance(odds: float, chests: int) -> float:
    if chests <= 0:
        return 0.0
    return (1.0 - ((1.0 - odds) ** chests)) * 100.0

# ==========================================
# BANCO DE DADOS (SQLite Local)
# ==========================================
def init_db():
    conn = sqlite3.connect("squad.db")
    c = conn.cursor()
    # Tabela de jogadores do squad
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            player_name TEXT PRIMARY KEY,
            total_chests INTEGER DEFAULT 0,
            last_match_chests INTEGER DEFAULT 0,
            matches_count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Tabela de configurações por servidor
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER PRIMARY KEY,
            milestone_interval INTEGER DEFAULT 1000,
            last_announced_milestone INTEGER DEFAULT 0,
            silent_mode INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_settings(guild_id: int):
    conn = sqlite3.connect("squad.db")
    c = conn.cursor()
    c.execute("SELECT milestone_interval, last_announced_milestone, silent_mode FROM settings WHERE guild_id = ?", (guild_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO settings (guild_id, milestone_interval, last_announced_milestone, silent_mode) VALUES (?, 1000, 0, 0)", (guild_id,))
        conn.commit()
        conn.close()
        return 1000, 0, 0
    conn.close()
    return row[0], row[1], row[2]

def update_settings(guild_id: int, milestone_interval=None, last_announced=None, silent_mode=None):
    conn = sqlite3.connect("squad.db")
    c = conn.cursor()
    if milestone_interval is not None:
        c.execute("UPDATE settings SET milestone_interval = ? WHERE guild_id = ?", (milestone_interval, guild_id))
    if last_announced is not None:
        c.execute("UPDATE settings SET last_announced_milestone = ? WHERE guild_id = ?", (last_announced, guild_id))
    if silent_mode is not None:
        c.execute("UPDATE settings SET silent_mode = ? WHERE guild_id = ?", (1 if silent_mode else 0, guild_id))
    conn.commit()
    conn.close()

def record_player_match(player_name: str, match_chests: int, reported_total: int):
    conn = sqlite3.connect("squad.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO players (player_name, total_chests, last_match_chests, matches_count)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(player_name) DO UPDATE SET
            total_chests = ?,
            last_match_chests = ?,
            matches_count = matches_count + 1,
            updated_at = CURRENT_TIMESTAMP
    """, (player_name, reported_total, match_chests, reported_total, match_chests))
    conn.commit()
    
    # Retorna o total geral somado do squad
    c.execute("SELECT SUM(total_chests), COUNT(*) FROM players")
    squad_total, active_players = c.fetchone()
    conn.close()
    return (squad_total or 0), active_players

def get_squad_leaderboard():
    conn = sqlite3.connect("squad.db")
    c = conn.cursor()
    c.execute("SELECT player_name, total_chests, matches_count FROM players ORDER BY total_chests DESC")
    rows = c.fetchall()
    c.execute("SELECT SUM(total_chests), SUM(matches_count) FROM players")
    totals = c.fetchone()
    conn.close()
    return rows, (totals[0] or 0), (totals[1] or 0)

# ==========================================
# EVENTOS DO DISCORD
# ==========================================
@bot.event
async def on_ready():
    init_db()
    try:
        synced = await bot.tree.sync()
        print(f"🤖 Bot do Squad online como {bot.user} ({len(synced)} slash commands ativos)")
    except Exception as e:
        print(f"Erro ao sincronizar comandos: {e}")

@bot.event
async def on_message(message: discord.Message):
    # Ignora mensagens enviadas pelo próprio bot
    if message.author.id == bot.user.id:
        return

    # Detecta se é o Webhook do ChestCounter
    # O ChestCounter envia embeds com título "Partida Finalizada!"
    if message.embeds:
        embed = message.embeds[0]
        if embed.title == "Partida Finalizada!" and embed.fields:
            player_name = (message.author.name or "Pirata").replace("🏴‍☠️", "").strip()
            
            match_chests = 0
            reported_total = 0

            # Extrai os dados dos campos do embed
            for f in embed.fields:
                if "Baús nesta Partida" in f.name:
                    m = re.search(r"\+?(\d+)", f.value)
                    if m: match_chests = int(m.group(1))
                elif "Total do Jogador" in f.name or "Total de Baús" in f.name:
                    # Remove pontos/vírgulas de formatação de milhar
                    clean_val = re.sub(r"[^\d]", "", f.value)
                    if clean_val: reported_total = int(clean_val)

            if reported_total > 0:
                squad_total, active_players = record_player_match(player_name, match_chests, reported_total)
                guild_id = message.guild.id if message.guild else 0
                interval, last_announced, silent_mode = get_settings(guild_id)

                # Verifica se o squad bateu uma nova meta (ex: a cada 1.000 baús)
                current_milestone = (squad_total // interval) * interval
                if current_milestone > last_announced and current_milestone > 0:
                    update_settings(guild_id, last_announced=current_milestone)
                    
                    token_odds = calc_chance(ODDS["token"], squad_total)
                    gold_odds = calc_chance(ODDS["gold_set"], squad_total)
                    vehicle_odds = calc_chance(ODDS["vehicle"], squad_total)

                    milestone_embed = discord.Embed(
                        title=f"🎉 META DO SQUAD ATINGIDA: {current_milestone:,} BAÚS! 🏴‍☠️",
                        description=f"O squad acumulou coletivamente **{squad_total:,} baús abertos** entre **{active_players} piratas ativos**!",
                        color=discord.Color.gold()
                    )
                    milestone_embed.add_field(name="🪙 Chance Coletiva do Token", value=f"**{token_odds:.3f}%** *(1 em 137.500)*", inline=True)
                    milestone_embed.add_field(name="👑 Conjunto Dourado", value=f"**{gold_odds:.5f}%** *(1 em 1.562.500)*", inline=True)
                    milestone_embed.add_field(name="🚗 Veículo & Adesivo", value=f"**{vehicle_odds:.2f}%** *(1 em 7.813)*", inline=True)
                    milestone_embed.set_footer(text=f"Próximo aviso quando o squad atingir {current_milestone + interval:,} baús!")

                    await message.channel.send(embed=milestone_embed)

                # Se o modo silencioso estiver ativado, apaga o relatório individual para não floodar
                if silent_mode:
                    try:
                        await message.delete()
                    except discord.Forbidden:
                        pass

    await bot.process_commands(message)

# ==========================================
# COMANDOS SLASH ( / )
# ==========================================

@bot.tree.command(name="squad", description="Mostra a somatória total de baús de todo o squad e as probabilidades!")
async def squad(interaction: discord.Interaction):
    rows, total_chests, total_matches = get_squad_leaderboard()
    if not rows:
        await interaction.response.send_message("❌ Nenhum dado registrado ainda! Abram o `ChestCounter.exe` e joguem uma partida.", ephemeral=True)
        return

    token_odds = calc_chance(ODDS["token"], total_chests)
    gold_odds = calc_chance(ODDS["gold_set"], total_chests)
    vehicle_odds = calc_chance(ODDS["vehicle"], total_chests)

    embed = discord.Embed(
        title="🏴‍☠️ Estatísticas Gerais do Squad (One Piece)",
        color=discord.Color.gold()
    )
    embed.add_field(name="📦 Total Somado do Squad", value=f"**{total_chests:,}** baús", inline=True)
    embed.add_field(name="🎮 Total de Partidas", value=f"**{total_matches}** partidas", inline=True)
    embed.add_field(name="🪙 Chance do Squad (Token)", value=f"**{token_odds:.4f}%**", inline=False)
    embed.add_field(name="👑 Conjunto Dourado Semanal", value=f"**{gold_odds:.5f}%**", inline=True)
    embed.add_field(name="🚗 Veículo Semanal", value=f"**{vehicle_odds:.2f}%**", inline=True)

    # Ranking dos membros
    leaderboard_lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, chests, matches) in enumerate(rows[:10]):
        prefix = medals[i] if i < 3 else f"`#{i+1}`"
        leaderboard_lines.append(f"{prefix} **{name}**: `{chests:,}` baús *({matches} partidas)*")

    embed.add_field(name="🏆 Placar dos Membros", value="\n".join(leaderboard_lines) if leaderboard_lines else "Nenhum", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="meta", description="Define de quantos em quantos baús do squad o bot deve anunciar no chat.")
@app_commands.describe(intervalo="Intervalo em baús (ex: 1000 para avisar a cada 1000 baús do squad)")
async def meta(interaction: discord.Interaction, intervalo: int):
    if intervalo < 10:
        await interaction.response.send_message("❌ O intervalo mínimo é de 10 baús.", ephemeral=True)
        return
    guild_id = interaction.guild_id or 0
    update_settings(guild_id, milestone_interval=intervalo)
    await interaction.response.send_message(f"✅ Meta configurada! O bot avisará no chat **apenas a cada {intervalo:,} baús** abertos pelo squad.")

@bot.tree.command(name="modo_silencioso", description="Ativa/Desativa o silenciamento das mensagens de cada partida individual.")
@app_commands.describe(ativo="True = apaga partidas individuais e avisa só nas metas | False = mostra tudo")
async def modo_silencioso(interaction: discord.Interaction, ativo: bool):
    guild_id = interaction.guild_id or 0
    update_settings(guild_id, silent_mode=ativo)
    status_str = "ativado (o chat só receberá mensagens nas metas de baús do squad)" if ativo else "desativado (todas as partidas serão exibidas)"
    await interaction.response.send_message(f"🔔 Modo silencioso **{status_str}**!")

@bot.tree.command(name="odds", description="Exibe a tabela oficial de probabilidades dos itens do evento de One Piece.")
async def odds(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎲 Probabilidades de Drop - Evento One Piece",
        description="Chances base por cada baú aberto no Fortnite:",
        color=discord.Color.blue()
    )
    embed.add_field(name="👑 Conjunto Dourado Semanal", value="`1 em 1.562.500` *(0,000064%)*", inline=False)
    embed.add_field(name="🪙 Acesso à Loja do Pirata (Token)", value="`1 em 137.500` *(0,000727%)*", inline=False)
    embed.add_field(name="🚗 Veículo Semanal e Adesivo", value="`1 em 7.813` *(0,0128%)*", inline=False)
    embed.add_field(name="⛏️ Picareta Semanal ou Mochila", value="`1 em 568` *(0,176%)*", inline=False)
    embed.add_field(name="🎵 Música Semanal", value="`1 em 391` *(0,256%)*", inline=False)
    embed.add_field(name="🖼️ Tela de Carregamento Semanal", value="`1 em 272` *(0,368%)*", inline=False)
    embed.add_field(name="🔮 Bugiganga (qualquer uma)", value="`1 em 127` *(0,787%)*", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="zerar_squad", description="Zera a contagem acumulada do squad para reiniciar o grind.")
async def zerar_squad(interaction: discord.Interaction):
    conn = sqlite3.connect("squad.db")
    c = conn.cursor()
    c.execute("DELETE FROM players")
    conn.commit()
    conn.close()
    guild_id = interaction.guild_id or 0
    update_settings(guild_id, last_announced=0)
    await interaction.response.send_message("🔄 Contagem do squad zerada com sucesso!")

if __name__ == "__main__":
    if BOT_TOKEN == "COLE_O_TOKEN_DO_SEU_BOT_AQUI":
        print("❌ Por favor, configure o BOT_TOKEN no arquivo squad_bot.py!")
    else:
        bot.run(BOT_TOKEN)
