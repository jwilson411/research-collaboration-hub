using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

public record HandoffContent(string StudyTitle, string StudySummary, string StudyStage, int SourceRevision,
    ProtocolDesignation? CurrentProtocol, List<Item> Items, List<StoredFile> Files,
    Dictionary<string, DocumentReviewState> DocumentReviews);
public record HandoffSnapshot(string Id, string Title, string Summary, string CreatedBy,
    DateTimeOffset CreatedAt, string RequestId, string Fingerprint, HandoffContent Content, string Sha256);
public record HandoffInput(string Title, string? Summary, string[]? ItemIds, string[]? FileIds,
    int ExpectedRevision, string RequestId);

/// <summary>Immutable captures, with current access/removal checks on every public projection.</summary>
public static class HandoffEndpoints
{
    const int MaximumItems = 50, MaximumFiles = 30, MaximumCaptureBytes = 1024 * 1024;
    static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    static readonly string[] DefaultKinds = ["document", "documentation", "decision", "task", "discussion"];

    public static void MapHandoffEndpoints(this WebApplication app,
        Func<HttpContext, string> identity, Func<State, string, Study, bool> access)
    {
        app.MapGet("/api/studies/{id}/handoffs", (string id, HttpContext context, IStudyStore store) =>
            store.Read<IResult>(state => {
                var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, identity(context), s));
                return study is null ? Results.NotFound() : Results.Ok(study.Handoffs.OrderByDescending(h => h.CreatedAt).Select(h => new {
                    h.Id, h.Title, h.Summary, h.CreatedBy, h.CreatedAt, sourceRevision = h.Content.SourceRevision,
                    h.Sha256, itemCount = h.Content.Items.Count, fileCount = h.Content.Files.Count }));
            }));
        app.MapGet("/api/studies/{id}/handoffs/{handoffId}", (string id, string handoffId, HttpContext context, IStudyStore store, AttachmentStorage storage) =>
            store.Read<IResult>(state => {
                var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, identity(context), s));
                var handoff = study?.Handoffs.FirstOrDefault(h => h.Id == handoffId);
                return handoff is null ? Results.NotFound() : Present(study!, handoff, storage);
            }));
        app.MapPost("/api/studies/{id}/handoffs", (string id, HandoffInput input, HttpContext context, IStudyStore store, AttachmentStorage storage) =>
            store.Change(state => {
                var actor = identity(context);
                var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, actor, s));
                if (study is null) return Results.NotFound();
                if (!Guid.TryParse(input.RequestId, out _) || string.IsNullOrWhiteSpace(input.Title) || input.Title.Length > 180 ||
                    input.Summary?.Length > 2000 || !ValidSelection(input.ItemIds, MaximumItems) || !ValidSelection(input.FileIds, MaximumFiles))
                    return Results.BadRequest(new { error = "Provide a title (1–180), optional summary (0–2000), up to 50 distinct item IDs and 30 distinct file IDs, and a request identifier." });
                var fingerprint = Hash(new { operation = "handoff", input });
                if (study.Requests.TryGetValue(input.RequestId, out var prior))
                    return prior == fingerprint && study.Handoffs.FirstOrDefault(h => h.RequestId == input.RequestId) is { } saved
                        ? Present(study, saved, storage) : Results.Conflict(new { error = "Request identifier belongs to another operation." });
                if (study.Stage != "Active" || study.Revision != input.ExpectedRevision)
                    return Results.Conflict(new { error = "Refresh the active study before capturing a handoff. Existing snapshots remain unchanged." });
                try
                {
                    var content = Capture(study, input, storage);
                    var now = DateTimeOffset.UtcNow;
                    var snapshot = new HandoffSnapshot(Guid.NewGuid().ToString(), input.Title.Trim(), input.Summary?.Trim() ?? "", actor, now,
                        input.RequestId, fingerprint, content, "");
                    snapshot = snapshot with { Sha256 = CaptureDigest(snapshot) };
                    study.Handoffs.Add(snapshot);
                    study.Requests.Add(input.RequestId, fingerprint);
                    study.Revision++;
                    state.Audit.Add(new(actor, "Captured immutable synthetic handoff " + snapshot.Id, study.Id, now));
                    return Present(study, snapshot, storage);
                }
                catch (InvalidDataException error) { return Results.BadRequest(new { error = error.Message }); }
            }));
    }

    static bool ValidSelection(string[]? values, int limit) => values is null ||
        values.Length <= limit && values.Distinct(StringComparer.Ordinal).Count() == values.Length &&
        values.All(id => !string.IsNullOrWhiteSpace(id) && id.Length <= 160);

    static HandoffContent Capture(Study study, HandoffInput input, AttachmentStorage storage)
    {
        var automatic = input.ItemIds is null && input.FileIds is null;
        var items = new HashSet<string>(automatic
            ? study.Items.Where(i => !i.Deleted && DefaultKinds.Contains(i.Kind)).Select(i => i.Id) : input.ItemIds ?? [], StringComparer.Ordinal);
        var files = new HashSet<string>(automatic
            ? study.Files.Where(f => !f.Deleted && f.ParentId is null).GroupBy(f => f.FamilyId).Select(g => g.OrderByDescending(f => f.Version).ThenBy(f => f.Id).First().Id)
            : input.FileIds ?? [], StringComparer.Ordinal);
        if (study.CurrentProtocol is { Kind: "item", Id: { } itemProtocol }) items.Add(itemProtocol);
        else if (study.CurrentProtocol is { Kind: "file", Id: { } fileProtocol }) files.Add(fileProtocol);

        // Include exact evidence and structural context, never substitute the newest version for a referenced ID.
        var visitedItems = new HashSet<string>();
        var visitedFiles = new HashSet<string>();
        while (visitedItems.Count != items.Count || visitedFiles.Count != files.Count)
        {
            if (items.Count > MaximumItems || files.Count > MaximumFiles)
                throw new InvalidDataException("The handoff and its linked evidence exceed 50 items or 30 files. Choose a smaller explicit record set.");
            foreach (var id in items.Where(id => !visitedItems.Contains(id)).ToArray())
            {
                var item = study.Items.FirstOrDefault(i => i.Id == id);
                if (item is null || !ItemAvailable(study, id))
                    throw new InvalidDataException("Selected records and linked evidence must be live records in this study.");
                visitedItems.Add(id);
                if (item.ParentId is not null) items.Add(item.ParentId);
                if (item.DocumentId is not null) items.Add(item.DocumentId);
                foreach (var reference in item.Task?.Links ?? []) items.Add(reference);
                foreach (var reference in item.FileIds.Concat(item.Task?.FileLinks ?? [])) files.Add(reference);
                foreach (var reference in item.Provenance?.ReferenceTargetIds ?? [])
                {
                    if (study.Items.Any(i => i.Id == reference)) items.Add(reference);
                    else if (study.Files.Any(f => f.Id == reference)) files.Add(reference);
                    else throw new InvalidDataException("A selected source record has unavailable evidence. Choose a record set with available evidence.");
                }
            }
            foreach (var id in files.Where(id => !visitedFiles.Contains(id)).ToArray())
            {
                var file = study.Files.FirstOrDefault(f => f.Id == id);
                if (file is null || !FileAvailable(study, file, storage))
                    throw new InvalidDataException("Selected file versions must be live, released, integrity-verified records in this study.");
                visitedFiles.Add(id);
                if (file.ParentId is not null) items.Add(file.ParentId);
                if (study.Items.Any(i => i.Id == file.FamilyId)) items.Add(file.FamilyId);
                foreach (var reference in file.Provenance?.ReferenceTargetIds ?? [])
                {
                    if (study.Items.Any(i => i.Id == reference)) items.Add(reference);
                    else if (study.Files.Any(f => f.Id == reference)) files.Add(reference);
                    else throw new InvalidDataException("A selected file version has unavailable source evidence.");
                }
            }
        }
        if (items.Count == 0 && files.Count == 0)
            throw new InvalidDataException("Choose at least one live study record for the handoff.");
        var copy = new HandoffContent(study.Title, study.Summary, study.Stage, study.Revision,
            study.CurrentProtocol, study.Items.Where(i => items.Contains(i.Id)).OrderBy(i => i.Id)
                .Select(i => i.Task is null ? i : i with { Task = i.Task with { History = [] } }).ToList(),
            study.Files.Where(f => files.Contains(f.Id)).OrderBy(f => f.Id).ToList(),
            study.DocumentReviews.Where(pair => items.Contains(pair.Key)).ToDictionary(pair => pair.Key, pair => pair.Value));
        var serialized = JsonSerializer.SerializeToUtf8Bytes(copy, Json);
        if (serialized.Length > MaximumCaptureBytes)
            throw new InvalidDataException("The immutable capture exceeds 1 MiB. Choose fewer records or shorter histories.");
        // Capture the current task version only; earlier task history remains on the live source.
        // Deep copy lists, current task state, review history and provenance before retaining the capture.
        return JsonSerializer.Deserialize<HandoffContent>(serialized, Json)!;
    }

    static IResult Present(Study study, HandoffSnapshot snapshot, AttachmentStorage storage) =>
        snapshot.Sha256 != CaptureDigest(snapshot)
            ? Results.Problem("Stored handoff integrity check failed. Its content is unavailable pending operator review.", statusCode: 503)
            : Results.Ok(Project(study, snapshot, storage));

    static object Project(Study study, HandoffSnapshot snapshot, AttachmentStorage storage)
    {
        var items = snapshot.Content.Items.Select(captured => {
            var available = ItemAvailable(study, captured.Id);
            var item = available ? captured : captured with {
                Title = "Removed study record", Body = "[Unavailable: the source record has been removed from current study access.]",
                ParentId = null, DocumentId = null, Task = null, FileIds = [], Provenance = null, Deleted = true };
            return new { item, available, reason = available ? null : "Source record removed or unavailable",
                review = available ? snapshot.Content.DocumentReviews.GetValueOrDefault(captured.Id) : null };
        }).ToArray();
        var files = snapshot.Content.Files.Select(captured => {
            var current = study.Files.FirstOrDefault(f => f.Id == captured.Id);
            var available = current is not null && current.Sha256 == captured.Sha256 && current.Size == captured.Size &&
                current.Version == captured.Version && current.FamilyId == captured.FamilyId && FileAvailable(study, current, storage);
            var file = available ? captured : captured with { Name = "Unavailable file version", Sha256 = "", Size = 0, ParentId = null, DocumentId = null,
                Provenance = null, Status = "Unavailable", Deleted = true };
            return new { file, available, reason = available ? null : "Source file removed, quarantined, or integrity check failed" };
        }).ToArray();
        var protocol = snapshot.Content.CurrentProtocol;
        var protocolAvailable = protocol is null || (protocol.Kind == "item" ? items.Any(i => i.item.Id == protocol.Id && i.available)
            : protocol.Kind == "file" && files.Any(f => f.file.Id == protocol.Id && f.available));
        return new { snapshot.Id, snapshot.Title, snapshot.Summary, snapshot.CreatedBy, snapshot.CreatedAt,
            sourceRevision = snapshot.Content.SourceRevision, snapshot.Sha256,
            digestScope = "Original immutable capture; projected removals do not alter digest. This is a content fingerprint, not a signature or approval.",
            studyTitle = snapshot.Content.StudyTitle, studySummary = snapshot.Content.StudySummary, studyStage = snapshot.Content.StudyStage,
            currentProtocol = protocol, protocolAvailable, items, files, redacted = items.Any(i => !i.available) || files.Any(f => !f.available) };
    }

    static bool ItemAvailable(Study study, string id)
    {
        var seen = new HashSet<string>();
        string? current = id;
        while (current is not null)
        {
            if (!seen.Add(current)) return false;
            var item = study.Items.FirstOrDefault(i => i.Id == current && !i.Deleted);
            if (item is null) return false;
            current = item.ParentId;
        }
        return true;
    }
    static bool FileAvailable(Study study, StoredFile file, AttachmentStorage storage) =>
        (file.ParentId is null || ItemAvailable(study, file.ParentId)) && EvidenceRules.FileAvailable(study, file.Id, storage);

    // Recompute internally after recovery against the unredacted stored capture, not the public view.
    public static string CaptureDigest(HandoffSnapshot snapshot) => Hash(new {
        snapshot.Id, snapshot.Title, snapshot.Summary, snapshot.CreatedBy, snapshot.CreatedAt, snapshot.Content });
    static string Hash<T>(T value)
    {
        var element = JsonSerializer.SerializeToElement(value, Json);
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream)) Canonical(writer, element);
        return Convert.ToHexString(SHA256.HashData(stream.ToArray()));
    }
    static void Canonical(Utf8JsonWriter writer, JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object) { writer.WriteStartObject(); foreach (var p in element.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal)) { writer.WritePropertyName(p.Name); Canonical(writer, p.Value); } writer.WriteEndObject(); }
        else if (element.ValueKind == JsonValueKind.Array) { writer.WriteStartArray(); foreach (var item in element.EnumerateArray()) Canonical(writer, item); writer.WriteEndArray(); }
        else element.WriteTo(writer);
    }
}
