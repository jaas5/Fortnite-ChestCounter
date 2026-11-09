using System.Net.Http;
using System.Text;
using System.Text.Json;

namespace ChestCounter;

public static class DiscordWebhook
{
    private static readonly HttpClient Http = new();

    /// <summary>
    /// URL padrão do Discord Webhook.
    /// Deixado vazio para o repositório público no GitHub (não vaza credenciais).
    /// Os usuários podem colar o Webhook diretamente nas Configurações do programa!
    /// </summary>
    public const string DefaultWebhookUrl = "";

    // Probabilidades exatas dos itens do evento de One Piece / Loja do Pirata
    private const double OddsGoldSet = 1.0 / 1562500.0;     // Conjunto Dourado Semanal: 1 em 1.562.500
    private const double OddsPirateToken = 1.0 / 137500.0;  // Acesso à Loja do Pirata (Token): 1 em 137.500
    private const double OddsVehicle = 1.0 / 7813.0;        // Veículo Semanal e Adesivo: 1 em 7.813
    private const double OddsPickaxe = 1.0 / 568.0;         // Picareta Semanal ou Mochila: 1 em 568
    private const double OddsMusic = 1.0 / 391.0;           // Música Semanal: 1 em 391
    private const double OddsLoadingScreen = 1.0 / 272.0;   // Tela de Carregamento Semanal: 1 em 272
    private const double OddsTrinket = 1.0 / 127.0;         // Bugiganga (qualquer uma): 1 em 127

    private static double CumulativeChance(double baseOdds, int chests)
    {
        if (chests <= 0) return 0.0;
        return (1.0 - Math.Pow(1.0 - baseOdds, chests)) * 100.0;
    }

    /// <summary>
    /// Sends a match notification to the specified Discord Webhook URL.
    /// Runs fire-and-forget in the background so it never blocks or slows down the replay tracker.
    /// </summary>
    public static void NotifyMatch(string? webhookUrl, MatchRecord match, int totalChests)
    {
        var targetUrl = !string.IsNullOrWhiteSpace(webhookUrl) ? webhookUrl : DefaultWebhookUrl;
        if (string.IsNullOrWhiteSpace(targetUrl))
        {
            return;
        }

        _ = Task.Run(async () =>
        {
            try
            {
                var playerName = match.PlayerName ?? "Pirata";
                var chestsMatch = match.ChestsOpened;
                var destroyed = match.Chests.Count(c => c.Destroyed);

                // Chances acumuladas baseadas no total de baús abertos
                var tokenChance = CumulativeChance(OddsPirateToken, totalChests);
                var goldSetChance = CumulativeChance(OddsGoldSet, totalChests);
                var vehicleChance = CumulativeChance(OddsVehicle, totalChests);
                var pickaxeChance = CumulativeChance(OddsPickaxe, totalChests);
                var musicChance = CumulativeChance(OddsMusic, totalChests);
                var loadingChance = CumulativeChance(OddsLoadingScreen, totalChests);
                var trinketChance = CumulativeChance(OddsTrinket, totalChests);

                var fields = new List<object>
                {
                    new { 
                        name = "📦 Baús nesta Partida", 
                        value = $"**+{chestsMatch}**" + (destroyed > 0 ? $" *({destroyed} destruídos)*" : ""), 
                        inline = true 
                    },
                    new { 
                        name = "🏆 Total do Jogador", 
                        value = $"**{totalChests:N0}** baús", 
                        inline = true 
                    },
                    new { 
                        name = "🪙 Token da Loja do Pirata", 
                        value = $"**{tokenChance:F3}%** *(1 em 137.500)*", 
                        inline = false 
                    },
                    new { 
                        name = "👑 Conjunto Dourado Semanal", 
                        value = $"**{goldSetChance:F5}%** *(1 em 1.562.500)*", 
                        inline = true 
                    },
                    new { 
                        name = "🚗 Veículo Semanal & Adesivo", 
                        value = $"**{vehicleChance:F2}%** *(1 em 7.813)*", 
                        inline = true 
                    },
                    new { 
                        name = "🎁 Outros Drops Acumulados", 
                        value = $"⛏️ **Picareta/Mochila:** {pickaxeChance:F1}% (1/568)\n🎵 **Música:** {musicChance:F1}% (1/391)\n🖼️ **Tela de Carregamento:** {loadingChance:F1}% (1/272)\n🔮 **Bugiganga:** {trinketChance:F1}% (1/127)", 
                        inline = false 
                    }
                };

                // Detalhes extras se disponíveis (Eliminações, Colocação)
                if (match.Placement.HasValue || match.Eliminations.HasValue)
                {
                    var extra = new List<string>();
                    if (match.Placement.HasValue) extra.Add($"🏆 #{match.Placement}");
                    if (match.Eliminations.HasValue) extra.Add($"⚔️ {match.Eliminations} eliminações");
                    fields.Add(new { name = "🎮 Desempenho", value = string.Join(" • ", extra), inline = false });
                }

                // Se encontrou algum item de tesouro/baú raro durante a partida
                if (match.TreasureFinds.Count > 0)
                {
                    var treasures = string.Join(", ", match.TreasureFinds.Select(t => t.DisplayName));
                    fields.Add(new { name = "🌟 TESOURO DROPADO NA PARTIDA!", value = $"**{treasures}**", inline = false });
                }

                var payload = new
                {
                    username = $"🏴‍☠️ {playerName}",
                    embeds = new[]
                    {
                        new
                        {
                            title = "Partida Finalizada!",
                            description = $"Relatório de caça aos baús atualizado.",
                            color = match.TreasureFinds.Count > 0 ? 15844367 : 16766720,
                            fields = fields.ToArray(),
                            footer = new
                            {
                                text = "Fortnite Treasure Hunters • One Piece Event"
                            },
                            timestamp = DateTime.UtcNow.ToString("o")
                        }
                    }
                };

                var json = JsonSerializer.Serialize(payload);
                using var content = new StringContent(json, Encoding.UTF8, "application/json");
                var response = await Http.PostAsync(targetUrl, content);
                if (!response.IsSuccessStatusCode)
                {
                    ErrorLog.Write("Discord webhook HTTP status", response.StatusCode);
                }
            }
            catch (Exception ex)
            {
                ErrorLog.Write("Erro ao enviar notificação para o Discord Webhook", ex);
            }
        });
    }
}
