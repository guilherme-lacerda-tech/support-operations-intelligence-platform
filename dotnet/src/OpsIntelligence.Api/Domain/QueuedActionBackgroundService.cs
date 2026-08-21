using Microsoft.Extensions.Options;

namespace OpsIntelligence.Api.Domain;

public sealed class QueuedActionBackgroundService : BackgroundService
{
    private readonly ActionProcessor _processor;
    private readonly OpsOptions _options;
    private readonly ILogger<QueuedActionBackgroundService> _logger;

    public QueuedActionBackgroundService(
        ActionProcessor processor,
        IOptions<OpsOptions> options,
        ILogger<QueuedActionBackgroundService> logger)
    {
        _processor = processor;
        _options = options.Value;
        _logger = logger;
    }

    public Task<MaintenanceResult> ProcessOnceAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(_processor.ProcessQueuedActions());
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await ProcessOnceAsync(stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception exc)
            {
                _logger.LogError(exc, "Queued action background processing failed");
            }

            await Task.Delay(_options.BackgroundPollMilliseconds, stoppingToken);
        }
    }
}
