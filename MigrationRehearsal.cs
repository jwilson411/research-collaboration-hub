using System.Text.Json;

public record RehearsalInventory(string SourceId, string? SourceStudyId, string? Kind, int? SourceRevision,
    int? VersionNumber, string? ParentId, string[] ReferenceIds, string Outcome, string[] Reasons,
    bool GroupMappingValid, string LegacyUrlStatus, string? LegacyUrlSha256, int UnsupportedReferenceCount);
public record RehearsalEvent(string Id, string Action, string Actor, DateTimeOffset At, string RequestId,
    int Revision, string State, string BeforeBranchSha256, string AfterBranchSha256, string ManifestSha256,
    ImportReport Report, List<RehearsalInventory> Inventory, string PreviousSha256, string Sha256);
public record MigrationRehearsal(string Id, string Actor, DateTimeOffset CreatedAt, string State, int Revision,
    Study Baseline, Study Branch, JsonElement Manifest, List<RehearsalEvent> History, string Sha256);
public record RehearsalCreateInput(JsonElement Manifest, int ExpectedRevision, string RequestId);
public record RehearsalActionInput(string Action, JsonElement? Manifest, int ExpectedRevision, string RequestId);

public static class MigrationRehearsalEndpoints
{
    const string Scope = "Isolated synthetic metadata rehearsal. Completeness covers only records submitted in this manifest, not a source-system inventory. No live content, permissions or attachment bytes are changed. Simulated file metadata is not a verified downloadable binary. Rollback restores only the isolated baseline.";
    static readonly JsonSerializerOptions Json = ImportReviewRules.Json;
    static string Hash<T>(T value) => ImportReviewRules.Hash(value);
    static Study Copy(Study source) => JsonSerializer.Deserialize<Study>(JsonSerializer.Serialize(new {
        source.Id, source.Title, source.Summary, source.Stage, source.GroupId, source.Revision, source.Items,
        source.Files, source.ImportLedger, source.DocumentReviews, source.CurrentProtocol
    }, Json), Json)!;
    static string[] Allowed(string state) => state switch {
        "Ready" => ["Apply", "Abort", "Rollback"], "Applied" => ["Delta", "Rollback"],
        "Aborted" => ["Retry", "Rollback"], "RolledBack" => ["Retry", "Delta"], _ => [] };
    static bool Valid(MigrationRehearsal session)
    {
        try {
            if (session.Sha256 != Hash(session with { Sha256 = "" }) || JsonSerializer.SerializeToUtf8Bytes(session, Json).Length > 2000000 || session.History.Count is < 1 or > 21 ||
                session.Revision != session.History.Count || JsonSerializer.SerializeToUtf8Bytes(session.Branch, Json).Length > 600000) return false;
            var previous = ""; var branchHash = Hash(session.Baseline);
            for (var i = 0; i < session.History.Count; i++) {
                var entry = session.History[i];
                if (entry.Revision != i + 1 || entry.PreviousSha256 != previous || entry.BeforeBranchSha256 != branchHash ||
                    entry.Sha256 != Hash(entry with { Sha256 = "" }) || entry.Inventory.Count != entry.Report.InputCount ||
                    entry.Report.Sha256 != ImportReviewRules.ReportHash(entry.Report)) return false;
                previous = entry.Sha256; branchHash = entry.AfterBranchSha256;
            }
            return branchHash == Hash(session.Branch) && session.State == session.History[^1].State &&
                session.History[^1].ManifestSha256 == Hash(session.Manifest);
        }
        catch (Exception error) when (error is NullReferenceException or ArgumentException or InvalidOperationException or OverflowException) { return false; }
    }
    static object Present(Study study, MigrationRehearsal session) => new {
        session.Id, session.Actor, session.CreatedAt, session.State, session.Revision, studyRevision = study.Revision,
        session.Sha256, scope = Scope, groupMappingCurrent = study.GroupId == session.Baseline.GroupId, allowedActions = study.GroupId == session.Baseline.GroupId ? Allowed(session.State) : [],
        inventory = session.History[^1].Inventory, report = PublicReport(session.History[^1].Report),
        history = session.History.Select(e => new { e.Id, e.Action, e.Actor, e.At, e.RequestId, e.Revision, e.State,
            e.BeforeBranchSha256, e.AfterBranchSha256, e.ManifestSha256, report = PublicReport(e.Report), e.Inventory, e.PreviousSha256, e.Sha256 }),
        branchSummary = new { items = session.Branch.Items.Count(i => !i.Deleted), files = session.Branch.Files.Count(f => !f.Deleted), ledgerEntries = session.Branch.ImportLedger.Count },
        baselineSha256 = Hash(session.Baseline), branchSha256 = Hash(session.Branch)
    };
    // Rehearsed target IDs never become download links or imply a committed import.
    static object PublicReport(ImportReport report) => new { report.InputCount, report.Counts, report.ManifestSha256,
        outcomes = report.Outcomes.Select(o => new { o.SourceId, o.SourceStudyId, o.SourceRevision, o.SourceKind, o.Status, o.Reasons }) };
    static IResult Corrupt() => Results.Problem("Rehearsal integrity check failed. Original study content was not changed.", statusCode: 503);
    static List<RehearsalInventory> Inventory(JsonElement manifest, ImportReport report) => manifest.GetProperty("records").EnumerateArray().Select(record => {
        string? Text(string name) => record.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;
        var outcome = report.Outcomes.Single(o => o.SourceId == Text("source_id"));
        var refs = record.TryGetProperty("references", out var references) && references.ValueKind == JsonValueKind.Array
            ? references.EnumerateArray().Where(r => r.ValueKind == JsonValueKind.String).Select(r => r.GetString()!).ToArray() : [];
        var version = record.TryGetProperty("version_number", out var v) && v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var ordinal) ? ordinal : (int?)null;
        var hasLegacy = record.TryGetProperty("legacy_url", out var legacy);
        var legacyStatus = !hasLegacy ? "NotProvided" : legacy.ValueKind == JsonValueKind.String && legacy.GetString() is { Length: > 0 and <= 2000 } url && !string.IsNullOrWhiteSpace(url) && !url.Any(char.IsControl) && Uri.TryCreate(url, UriKind.Absolute, out var uri) &&
            uri.Scheme is "http" or "https" && !string.IsNullOrEmpty(uri.Host) && string.IsNullOrEmpty(uri.UserInfo) ? "RecordedHttpReferenceNotFetched" : "UnsupportedReference";
        var unsupportedReferences = record.TryGetProperty("references", out var rawRefs) ? rawRefs.ValueKind == JsonValueKind.Array
            ? rawRefs.EnumerateArray().Count(r => r.ValueKind != JsonValueKind.String || r.GetString() is not { Length: > 0 and <= 160 } reference || !reference.All(c => char.IsAsciiLetterOrDigit(c) || c is '-' or '_' or '.' or ':')) : 1 : 0;
        return new RehearsalInventory(outcome.SourceId, outcome.SourceStudyId, outcome.SourceKind, outcome.SourceRevision, version,
            Text("parent_id"), refs, outcome.Status, outcome.Reasons, !outcome.Reasons.Contains("unresolved_or_mismatched_group_mapping"), legacyStatus, hasLegacy ? Hash(legacy) : null, unsupportedReferences);
    }).ToList();
    static MigrationRehearsal Advance(MigrationRehearsal session, string action, string actor, string requestId,
        string state, Study branch, JsonElement manifest, ImportReport report)
    {
        var entry = new RehearsalEvent(Guid.NewGuid().ToString(), action, actor, DateTimeOffset.UtcNow, requestId,
            session.Revision + 1, state, Hash(session.Branch), Hash(branch), Hash(manifest), report,
            Inventory(manifest, report), session.History.LastOrDefault()?.Sha256 ?? "", "");
        entry = entry with { Sha256 = Hash(entry) };
        var result = session with { State = state, Revision = entry.Revision, Branch = branch, Manifest = manifest.Clone(),
            History = session.History.Append(entry).ToList(), Sha256 = "" };
        return result with { Sha256 = Hash(result) };
    }
    static bool Fits(Study study, MigrationRehearsal session)
    {
        var size = JsonSerializer.SerializeToUtf8Bytes(session, Json).Length;
        return size <= 2000000 && size + study.MigrationRehearsals.Where(s => s.Id != session.Id)
            .Sum(s => (long)JsonSerializer.SerializeToUtf8Bytes(s, Json).Length) <= 4000000;
    }
    static IResult Safe(Func<IResult> action)
    {
        try { return action(); }
        catch (InvalidDataException) { return Results.BadRequest(new { error = "Use a bounded valid synthetic manifest with unique source IDs and at most 100 records." }); }
        catch (JsonException) { return Results.BadRequest(new { error = "Invalid synthetic manifest JSON." }); }
    }
    public static void MapMigrationRehearsalEndpoints(this WebApplication app, Func<HttpContext, string> identity,
        Func<State, string, Study, bool> access)
    {
        Study? Authorized(State state, string id, string actor) => state.Roles.GetValueOrDefault(actor) == "Administrator"
            ? state.Studies.FirstOrDefault(s => s.Id == id && access(state, actor, s)) : null;
        app.MapGet("/api/studies/{id}/imports/rehearsals", (string id, HttpContext context, IStudyStore store) => store.Read<IResult>(state => {
            var study = Authorized(state, id, identity(context)); if (study is null) return Results.NotFound();
            if (study.MigrationRehearsals.Any(s => !Valid(s))) return Corrupt();
            return Results.Ok(new { studyRevision = study.Revision, scope = Scope, sessions = study.MigrationRehearsals.Select(s => new { s.Id, s.State, s.Revision, s.CreatedAt, s.Actor, s.Sha256 }) });
        }));
        foreach (var export in new[] { false, true })
            app.MapGet("/api/studies/{id}/imports/rehearsals/{sessionId}" + (export ? "/export" : ""),
                (string id, string sessionId, HttpContext context, IStudyStore store) => store.Read<IResult>(state => {
                    var study = Authorized(state, id, identity(context)); if (study is null) return Results.NotFound();
                    var session = study.MigrationRehearsals.FirstOrDefault(s => s.Id == sessionId); if (session is null) return Results.NotFound();
                    if (!Valid(session)) return Corrupt();
                    var view = Present(study, session);
                    return export ? Results.File(JsonSerializer.SerializeToUtf8Bytes(new { receipt = view, receiptSha256 = Hash(view) }, Json), "application/json", "synthetic-rehearsal-" + session.Id + ".json") : Results.Ok(view);
                }));
        app.MapPost("/api/studies/{id}/imports/rehearsals", (string id, RehearsalCreateInput input, HttpContext context, IStudyStore store, AttachmentStorage storage) => Safe(() => store.Change(state => {
            var actor = identity(context); var study = Authorized(state, id, actor); if (study is null) return Results.NotFound();
            if (study.MigrationRehearsals.Any(s => !Valid(s))) return Corrupt();
            if (!Guid.TryParse(input.RequestId, out _) || input.ExpectedRevision < 1 || input.Manifest.ValueKind != JsonValueKind.Object) return Results.BadRequest();
            var fingerprint = Hash(new { operation = "rehearsal-create", input });
            if (study.Requests.TryGetValue(input.RequestId, out var prior)) {
                var saved = study.MigrationRehearsals.FirstOrDefault(s => s.History[0].RequestId == input.RequestId);
                return prior == fingerprint && saved is not null ? Results.Ok(Present(study, saved)) : Results.Conflict();
            }
            if (study.Stage != "Active" || study.Revision != input.ExpectedRevision) return Results.Conflict(new { error = "Refresh the active study before creating an isolated rehearsal." });
            if (study.MigrationRehearsals.Count >= 3) return Results.Conflict(new { error = "This bounded preview permits three rehearsal sessions per study." });
            var baseline = Copy(study);
            if (JsonSerializer.SerializeToUtf8Bytes(baseline, Json).Length > 500000) return Results.BadRequest(new { error = "This study exceeds the bounded rehearsal baseline size." });
            var branch = Copy(baseline); var report = SyntheticImportEndpoints.Simulate(branch, input.Manifest, storage, false);
            var session = new MigrationRehearsal(Guid.NewGuid().ToString(), actor, DateTimeOffset.UtcNow, "Ready", 0,
                baseline, branch, input.Manifest.Clone(), [], "");
            session = Advance(session, "Create", actor, input.RequestId, "Ready", branch, input.Manifest, report);
            if (!Fits(study, session)) return Results.BadRequest(new { error = "Rehearsal metadata exceeds the bounded storage budget." });
            study.MigrationRehearsals.Add(session); study.Requests.Add(input.RequestId, fingerprint); study.Revision++;
            state.Audit.Add(new(actor, "Created isolated synthetic migration rehearsal", study.Id, DateTimeOffset.UtcNow));
            return Results.Ok(Present(study, session));
        })));
        app.MapPost("/api/studies/{id}/imports/rehearsals/{sessionId}/actions", (string id, string sessionId, RehearsalActionInput input,
            HttpContext context, IStudyStore store, AttachmentStorage storage) => Safe(() => store.Change(state => {
                var actor = identity(context); var study = Authorized(state, id, actor); if (study is null) return Results.NotFound();
                var session = study.MigrationRehearsals.FirstOrDefault(s => s.Id == sessionId); if (session is null) return Results.NotFound();
                if (!Valid(session)) return Corrupt();
                if (!Guid.TryParse(input.RequestId, out _) || input.ExpectedRevision < 1 || input.Action is not ("Apply" or "Abort" or "Retry" or "Delta" or "Rollback")) return Results.BadRequest();
                var fingerprint = Hash(new { operation = "rehearsal-action", sessionId, input });
                if (study.Requests.TryGetValue(input.RequestId, out var prior)) return prior == fingerprint && session.History.Any(e => e.RequestId == input.RequestId)
                    ? Results.Ok(Present(study, session)) : Results.Conflict();
                if (study.Stage != "Active" || study.GroupId != session.Baseline.GroupId || session.Revision != input.ExpectedRevision || !Allowed(session.State).Contains(input.Action))
                    return Results.Conflict(new { error = "Refresh the active study and current rehearsal state before this action." });
                if (session.History.Count >= 21) return Results.Conflict(new { error = "This bounded rehearsal permits twenty actions after creation." });
                if (input.Action == "Delta" && input.Manifest is null || input.Action != "Delta" && input.Manifest is not null)
                    return Results.BadRequest(new { error = "Only Delta accepts a new manifest, and requires one." });
                var manifest = input.Action == "Delta" ? input.Manifest!.Value : session.Manifest;
                var branch = input.Action == "Rollback" ? Copy(session.Baseline) : Copy(session.Branch);
                var report = SyntheticImportEndpoints.Simulate(branch, manifest, storage, input.Action == "Apply");
                if (JsonSerializer.SerializeToUtf8Bytes(branch, Json).Length > 600000) return Results.BadRequest(new { error = "Rehearsed branch exceeds the bounded preview size." });
                var next = input.Action switch { "Apply" => "Applied", "Abort" => "Aborted", "Rollback" => "RolledBack", _ => "Ready" };
                var updated = Advance(session, input.Action, actor, input.RequestId, next, branch, manifest, report);
                if (!Fits(study, updated)) return Results.BadRequest(new { error = "Rehearsal metadata exceeds the bounded storage budget." });
                study.MigrationRehearsals[study.MigrationRehearsals.IndexOf(session)] = updated;
                study.Requests.Add(input.RequestId, fingerprint); study.Revision++;
                state.Audit.Add(new(actor, "Isolated migration rehearsal " + input.Action, study.Id, DateTimeOffset.UtcNow));
                return Results.Ok(Present(study, updated));
            })));
    }
}
