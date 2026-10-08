using System.Security.Cryptography;
using System.Text.Json;

public record ImportReviewEvent(string Id, string ReportId, string ReportSha256, string SourceId,
    string OwnerId, string Action, string State, string Disposition, string Note, string? SuccessorReportId,
    string Actor, DateTimeOffset At, string RequestId, int StudyRevision, string PreviousSha256, string Sha256);
public record ImportCaseSnapshot(string ReportId, string SourceId, string Status, string[] Reasons,
    string? OwnerId, string State, string? Disposition, List<ImportReviewEvent> History);
public record ImportReceipt(string Id, string ReportId, string Actor, DateTimeOffset At, string RequestId,
    int StudyRevision, ImportReport Report, List<ImportCaseSnapshot> Cases, string Scope, string Sha256);
public record ImportReviewInput(string SourceId, string OwnerId, string Action, string Disposition,
    string Note, string? SuccessorReportId, int ExpectedRevision, string RequestId);
public record ImportReceiptInput(int ExpectedRevision, string RequestId);

public static class ImportReviewRules
{
    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    public static string Hash<T>(T value) => Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(value, Json)));
    public static string ReportHash(ImportReport report) => Hash(report with { Sha256 = null });
    public static bool ValidReport(ImportReport report) => report.Applied && report.InputCount == report.Outcomes.Count &&
        report.Outcomes.All(outcome => outcome is not null && outcome.Reasons is not null && outcome.Reasons.All(reason => reason is not null)) &&
        report.Outcomes.Select(o => o.SourceId).Distinct().Count() == report.InputCount &&
        report.Counts.Values.Sum(value => (long)value) == report.InputCount && report.Counts.All(p => p.Value == report.Outcomes.Count(o => o.Status == p.Key)) &&
        (report.Sha256 is null || report.Sha256 == ReportHash(report));
    public static bool Valid(Study study)
    {
        try { return ValidateStructure(study); }
        catch (Exception error) when (error is NullReferenceException or ArgumentException or InvalidOperationException or OverflowException)
        { return false; }
    }
    static bool ValidateStructure(Study study)
    {
        if (study.ImportReports.Any(r => !ValidReport(r))) return false;
        var previous = "";
        foreach (var entry in study.ImportReviewEvents)
        {
            var report = study.ImportReports.FirstOrDefault(r => r.Id == entry.ReportId);
            if (report is null || entry.ReportSha256 != ReportHash(report) || entry.PreviousSha256 != previous ||
                entry.Sha256 != Hash(entry with { Sha256 = "" })) return false;
            previous = entry.Sha256;
        }
        foreach (var receipt in study.ImportReceipts)
        {
            var report = study.ImportReports.FirstOrDefault(r => r.Id == receipt.ReportId);
            if (report is null || ReportHash(report) != ReportHash(receipt.Report) || receipt.Sha256 != Hash(receipt with { Sha256 = "" })) return false;
        }
        return true;
    }
    public static ImportCaseSnapshot Case(Study study, ImportReport report, ImportOutcome outcome)
    {
        var history = study.ImportReviewEvents.Where(e => e.ReportId == report.Id && e.SourceId == outcome.SourceId).ToList();
        var latest = history.LastOrDefault();
        return new(report.Id, outcome.SourceId, outcome.Status, outcome.Reasons.ToArray(), latest?.OwnerId,
            latest?.State ?? "Open", latest?.Disposition, history);
    }
    public static IEnumerable<ImportCaseSnapshot> Cases(Study study, ImportReport report) => report.Outcomes
        .Where(o => o.Status is "quarantined" or "stale_ignored").Select(o => Case(study, report, o));
}

public static class ImportReviewEndpoints
{
    const string Scope = "Synthetic submitted batch only. Operator disposition does not accept content, override quarantine, grant access, or establish complete source inventory.";
    static IResult Corrupt() => Results.Problem("Import review integrity check failed; no receipt or review was changed.", statusCode: 503);
    public static void MapImportReviewEndpoints(this WebApplication app, Func<HttpContext, string> identity,
        Func<State, string, Study, bool> access)
    {
        Study? Authorized(State state, string id, string actor) => state.Roles.GetValueOrDefault(actor) == "Administrator"
            ? state.Studies.FirstOrDefault(s => s.Id == id && access(state, actor, s)) : null;
        app.MapGet("/api/studies/{id}/imports/review", (string id, HttpContext context, IStudyStore store) => store.Read<IResult>(state => {
            var study = Authorized(state, id, identity(context));
            if (study is null) return Results.NotFound();
            if (!ImportReviewRules.Valid(study)) return Corrupt();
            return Results.Ok(new { studyRevision = study.Revision, cases = study.ImportReports.SelectMany(r => ImportReviewRules.Cases(study, r)),
                receipts = study.ImportReceipts.Select(r => new { r.Id, r.ReportId, r.At, r.Actor, r.StudyRevision, r.Sha256 }), scope = Scope });
        }));
        foreach (var export in new[] { false, true })
            app.MapGet("/api/studies/{id}/imports/receipts/{receiptId}" + (export ? "/export" : ""),
                (string id, string receiptId, HttpContext context, IStudyStore store) => store.Read<IResult>(state => {
                    var study = Authorized(state, id, identity(context));
                    if (study is null) return Results.NotFound();
                    if (!ImportReviewRules.Valid(study)) return Corrupt();
                    var receipt = study.ImportReceipts.FirstOrDefault(r => r.Id == receiptId);
                    if (receipt is null) return Results.NotFound();
                    return export ? Results.File(JsonSerializer.SerializeToUtf8Bytes(receipt, ImportReviewRules.Json), "application/json",
                        "synthetic-import-receipt-" + receipt.Id + ".json") : Results.Ok(receipt);
                }));
        app.MapPost("/api/studies/{id}/imports/{reportId}/review", (string id, string reportId, ImportReviewInput input,
            HttpContext context, IStudyStore store) => store.Change(state => {
                var actor = identity(context); var study = Authorized(state, id, actor);
                if (study is null) return Results.NotFound();
                if (!ImportReviewRules.Valid(study)) return Corrupt();
                if (!Guid.TryParse(input.RequestId, out _) || input.ExpectedRevision < 1 || string.IsNullOrWhiteSpace(input.SourceId) || input.SourceId.Length > 200 || input.SuccessorReportId?.Length > 100 ||
                    string.IsNullOrWhiteSpace(input.OwnerId) || input.OwnerId.Length > 100 || string.IsNullOrWhiteSpace(input.Note) || input.Note.Length > 1000 ||
                    input.Action is not ("Assign" or "Review" or "Resolve" or "Reopen") ||
                    input.Disposition is not ("NeedsCorrection" or "Excluded" or "CorrectedInLaterImport"))
                    return Results.BadRequest(new { error = "Provide a source ID, current member owner, action, disposition, note (1–1000), revision and request ID." });
                var report = study.ImportReports.FirstOrDefault(r => r.Id == reportId);
                var outcome = report?.Outcomes.FirstOrDefault(o => o.SourceId == input.SourceId && o.Status is "quarantined" or "stale_ignored");
                if (report is null || outcome is null) return Results.NotFound();
                var fingerprint = ImportReviewRules.Hash(new { operation = "import-review", reportId, input });
                if (study.Requests.TryGetValue(input.RequestId, out var prior))
                    return prior == fingerprint && study.ImportReviewEvents.FirstOrDefault(e => e.RequestId == input.RequestId) is { } saved
                        ? Results.Ok(new { studyRevision = study.Revision, @case = ImportReviewRules.Case(study, report, outcome), savedEvent = saved })
                        : Results.Conflict(new { error = "Request ID already belongs to another operation." });
                if (study.Stage != "Active" || study.Revision != input.ExpectedRevision)
                    return Results.Conflict(new { error = "Refresh the active study before recording an operator disposition." });
                if (!Demo.Identities.Any(i => i.Id == input.OwnerId) || !Demo.Groups.GetValueOrDefault(input.OwnerId, []).Contains(study.GroupId))
                    return Results.BadRequest(new { error = "Owner must currently belong to the study group; assignment never grants access." });
                var current = ImportReviewRules.Case(study, report, outcome);
                if (current.State == "Resolved" && input.Action != "Reopen" || current.State != "Resolved" && input.Action == "Reopen")
                    return Results.Conflict(new { error = "Resolved tracking must explicitly reopen before another review." });
                if (input.Action is "Assign" or "Reopen" && (input.Disposition != "NeedsCorrection" || input.SuccessorReportId is not null) ||
                    input.Action == "Review" && (input.Disposition != "NeedsCorrection" || input.SuccessorReportId is not null) ||
                    input.Action == "Resolve" && input.Disposition == "NeedsCorrection")
                    return Results.BadRequest(new { error = "Assign/review/reopen use NeedsCorrection; resolve uses Excluded or CorrectedInLaterImport." });
                if (input.Action is "Review" or "Resolve" && current.OwnerId is null)
                    return Results.Conflict(new { error = "Assign an owner before reviewing or resolving an exception." });
                if (input.Action is "Review" or "Resolve" && input.OwnerId != current.OwnerId)
                    return Results.Conflict(new { error = "Reassign ownership explicitly before reviewing or resolving." });
                if (input.Disposition == "CorrectedInLaterImport")
                {
                    var successor = study.ImportReports.FirstOrDefault(r => r.Id == input.SuccessorReportId && r.StudyRevision > report.StudyRevision);
                    if (successor is null || !successor.Outcomes.Any(o => o.SourceId == input.SourceId && outcome.SourceStudyId is not null && o.SourceStudyId == outcome.SourceStudyId && outcome.SourceKind is not null && o.SourceKind == outcome.SourceKind && outcome.SourceRevision is not null && o.SourceRevision >= outcome.SourceRevision && o.Status is "imported" or "unchanged" or "deleted"))
                        return Results.BadRequest(new { error = "Correction requires a later applied report in this study with the same source ID and an accepted automatic outcome." });
                }
                else if (input.SuccessorReportId is not null) return Results.BadRequest(new { error = "Only a corrected disposition can cite a later report." });
                var nextState = input.Action switch { "Assign" => "Assigned", "Review" => "Reviewed", "Resolve" => "Resolved", _ => "Open" };
                var entry = new ImportReviewEvent(Guid.NewGuid().ToString(), reportId, ImportReviewRules.ReportHash(report), input.SourceId,
                    input.OwnerId, input.Action, nextState, input.Disposition, input.Note.Trim(), input.SuccessorReportId, actor,
                    DateTimeOffset.UtcNow, input.RequestId, study.Revision + 1, study.ImportReviewEvents.LastOrDefault()?.Sha256 ?? "", "");
                entry = entry with { Sha256 = ImportReviewRules.Hash(entry) };
                study.ImportReviewEvents.Add(entry); study.Requests.Add(input.RequestId, fingerprint); study.Revision++;
                state.Audit.Add(new(actor, "Import exception " + input.Action + "; " + input.Disposition, study.Id, entry.At));
                return Results.Ok(new { studyRevision = study.Revision, @case = ImportReviewRules.Case(study, report, outcome), savedEvent = entry });
            }));
        app.MapPost("/api/studies/{id}/imports/{reportId}/receipts", (string id, string reportId, ImportReceiptInput input,
            HttpContext context, IStudyStore store) => store.Change(state => {
                var actor = identity(context); var study = Authorized(state, id, actor);
                if (study is null) return Results.NotFound();
                if (!ImportReviewRules.Valid(study)) return Corrupt();
                if (!Guid.TryParse(input.RequestId, out _) || input.ExpectedRevision < 1) return Results.BadRequest();
                var fingerprint = ImportReviewRules.Hash(new { operation = "import-receipt", reportId, input });
                if (study.Requests.TryGetValue(input.RequestId, out var prior))
                    return prior == fingerprint && study.ImportReceipts.FirstOrDefault(r => r.RequestId == input.RequestId) is { } saved
                        ? Results.Ok(saved) : Results.Conflict(new { error = "Request ID already belongs to another operation." });
                if (study.Stage != "Active" || study.Revision != input.ExpectedRevision) return Results.Conflict(new { error = "Refresh the active study before capturing a receipt." });
                var report = study.ImportReports.FirstOrDefault(r => r.Id == reportId);
                if (report is null) return Results.NotFound();
                var receipt = new ImportReceipt(Guid.NewGuid().ToString(), reportId, actor, DateTimeOffset.UtcNow, input.RequestId,
                    study.Revision + 1, report, ImportReviewRules.Cases(study, report).ToList(), Scope, "");
                receipt = JsonSerializer.Deserialize<ImportReceipt>(JsonSerializer.Serialize(receipt, ImportReviewRules.Json), ImportReviewRules.Json)!;
                receipt = receipt with { Sha256 = ImportReviewRules.Hash(receipt) };
                study.ImportReceipts.Add(receipt); study.Requests.Add(input.RequestId, fingerprint); study.Revision++;
                state.Audit.Add(new(actor, "Captured synthetic batch reconciliation receipt", study.Id, receipt.At));
                return Results.Ok(receipt);
            }));
    }
}
