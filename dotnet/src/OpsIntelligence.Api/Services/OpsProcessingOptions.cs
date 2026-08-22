namespace OpsIntelligence.Api.Services;

public sealed class OpsProcessingOptions
{
    public const string SectionName = "OpsProcessing";

    public int CooldownSeconds { get; init; } = 300;
    public int RetryDelayMilliseconds { get; init; } = 100;
    public int MaxActionAttempts { get; init; } = 3;
    public int WorkerBatchSize { get; init; } = 100;
    public int WorkerPollMilliseconds { get; init; } = 250;
    public bool WorkerEnabled { get; init; } = true;

    public TimeSpan Cooldown => TimeSpan.FromSeconds(Math.Max(0, CooldownSeconds));
    public TimeSpan RetryDelay => TimeSpan.FromMilliseconds(Math.Max(0, RetryDelayMilliseconds));
    public TimeSpan WorkerPollInterval => TimeSpan.FromMilliseconds(Math.Max(10, WorkerPollMilliseconds));
}
