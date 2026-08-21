namespace OpsIntelligence.Api.Domain;

public sealed class OpsOptions
{
    public string DatabasePath { get; set; } = "ops-intelligence-cleanroom.sqlite3";
    public int CooldownMinutes { get; set; } = 20;
    public int MaxActionAttempts { get; set; } = 3;
    public int BackgroundPollMilliseconds { get; set; } = 5_000;
    public bool UseWal { get; set; }
    public bool EnableBackgroundProcessor { get; set; }

    public string ConnectionString => $"Data Source={DatabasePath};Cache=Shared;Pooling=True";

    public void ApplyEnvironment()
    {
        DatabasePath = Environment.GetEnvironmentVariable("OPS_DB_PATH") ?? DatabasePath;
        UseWal = ReadBool("OPS_SQLITE_WAL", UseWal);
        EnableBackgroundProcessor = ReadBool("OPS_ENABLE_BACKGROUND", EnableBackgroundProcessor);
    }

    private static bool ReadBool(string key, bool defaultValue)
    {
        var value = Environment.GetEnvironmentVariable(key);
        if (string.IsNullOrWhiteSpace(value))
        {
            return defaultValue;
        }

        return value.Equals("1", StringComparison.OrdinalIgnoreCase)
            || value.Equals("true", StringComparison.OrdinalIgnoreCase)
            || value.Equals("yes", StringComparison.OrdinalIgnoreCase);
    }
}
