using Microsoft.Extensions.Options;

namespace OpsIntelligence.Api.Services;

public sealed class ActionWorker : BackgroundService
{
    private readonly ActionProcessor _processor;
    private readonly IActionSignalQueue _queue;
    private readonly OpsProcessingOptions _options;

    public ActionWorker(
        ActionProcessor processor,
        IActionSignalQueue queue,
        IOptions<OpsProcessingOptions> options)
    {
        _processor = processor;
        _queue = queue;
        _options = options.Value;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            await _processor.ProcessPendingAsync(_options.WorkerBatchSize, stoppingToken);
            await _queue.WaitForSignalOrDelayAsync(_options.WorkerPollInterval, stoppingToken);
        }
    }
}
