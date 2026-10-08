using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

public record SourceProvenance(string SourceStudyId, string SourceId, int SourceRevision,
    string Fingerprint, string? FamilyId, string[] ReferenceTargetIds, JsonElement Original);
public record ImportEntry(string SourceStudyId, string SourceId, int SourceRevision, string Fingerprint,
    string TargetId, string Kind, string TargetFingerprint, bool Deleted, SourceProvenance Source,
    List<SourceProvenance> History);
public record ImportOutcome(string SourceId, string Status, string[] Reasons, string? TargetId);
public record ImportReport(string Id, string? RequestId, DateTimeOffset At, bool Applied, int StudyRevision,
    int InputCount, Dictionary<string, int> Counts, List<ImportOutcome> Outcomes, string ManifestSha256);
public record ImportPreviewInput(JsonElement Manifest);
public record ImportApplyInput(JsonElement Manifest, int ExpectedRevision, string RequestId);

public static class SyntheticImportEndpoints
{
    static readonly string[] Kinds = ["document", "version", "discussion", "reply", "attachment", "decision"];
    static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    public static void MapSyntheticImportEndpoints(this WebApplication app,
        Func<HttpContext, string> identity, Func<State, string, Study, bool> access)
    {
        Study? Authorized(State state, string id, string user) => state.Roles.GetValueOrDefault(user) == "Administrator"
            ? state.Studies.FirstOrDefault(s => s.Id == id && access(state, user, s)) : null;
        app.MapMethods("/api/studies/{id}/imports/preview", ["GET", "HEAD"], () => Results.StatusCode(405));
        app.MapMethods("/api/studies/{id}/imports/apply", ["GET", "HEAD"], () => Results.StatusCode(405));
        app.MapPost("/api/studies/{id}/imports/preview", (string id, ImportPreviewInput input, HttpContext context, IStudyStore store, AttachmentStorage files) =>
            Safe(() => store.Read<IResult>(state => {
                var study = Authorized(state, id, identity(context));
                if (study is null) return Results.NotFound();
                var plan = Plan(study, input.Manifest, files);
                return Results.Ok(Report(study, plan, null, false));
            })));
        app.MapGet("/api/studies/{id}/imports", (string id, HttpContext context, IStudyStore store) =>
            store.Read<IResult>(state => Authorized(state, id, identity(context)) is { } study
                ? Results.Ok(study.ImportReports) : Results.NotFound()));
        app.MapPost("/api/studies/{id}/imports/apply", (string id, ImportApplyInput input, HttpContext context, IStudyStore store, AttachmentStorage files) =>
            Safe(() => store.Change(state => {
                var study = Authorized(state, id, identity(context));
                if (study is null) return Results.NotFound();
                if (!Guid.TryParse(input.RequestId, out _)) return Results.BadRequest(new { error = "A request identifier is required." });
                ValidateManifest(input.Manifest);
                var operation = Hash(new { operation = "synthetic-import", manifest = input.Manifest, input.ExpectedRevision });
                if (study.Requests.TryGetValue(input.RequestId, out var previous))
                    return previous == operation && study.ImportReports.FirstOrDefault(r => r.RequestId == input.RequestId) is { } saved
                        ? Results.Ok(saved) : Results.Conflict(new { error = "Request identifier was already used for another operation." });
                if (study.Stage != "Active" || study.Revision != input.ExpectedRevision)
                    return Results.Conflict(new { error = "Refresh the active study and preview again before applying." });
                var plan = Plan(study, input.Manifest, files);
                Apply(study, plan, files);
                study.Revision++;
                var report = Report(study, plan, input.RequestId, true);
                study.ImportReports.Add(report);
                study.Requests.Add(input.RequestId, operation);
                state.Audit.Add(new(identity(context), "Applied synthetic import; quarantined " + report.Counts["quarantined"], study.Id, DateTimeOffset.UtcNow));
                return Results.Ok(report);
            })));
    }

    sealed class Candidate(JsonElement source, string sourceId, string targetId)
    {
        public JsonElement Source = source;
        public string SourceId = sourceId, TargetId = targetId, Kind = "", SourceStudyId = "", Fingerprint = "", Status = "imported";
        public int Revision;
        public bool Deleted;
        public DateTimeOffset At;
        public string Author = "", Title = "", Body = "", Filename = "";
        public string? Parent;
        public string[] References = [];
        public byte[]? Bytes;
        public List<string> Reasons = [];
    }
    sealed record ImportPlan(string Fingerprint, List<Candidate> Candidates);

    static ImportPlan Plan(Study study, JsonElement manifest, AttachmentStorage files)
    {
        ValidateManifest(manifest);
        var candidates = new List<Candidate>();
        foreach (var record in manifest.GetProperty("records").EnumerateArray())
        {
            var sid = Text(record, "source_id");
            study.ImportLedger.TryGetValue(sid, out var old);
            // Deterministic IDs make previews repeatable without creating paths or files.
            var target = old?.TargetId ?? Hash(new { study.Id, source = sid, sourceStudy = Text(record, "study_id") })[..32].ToLowerInvariant();
            var c = new Candidate(record, sid, target) { Kind = Text(record, "kind"), SourceStudyId = Text(record, "study_id"),
                Fingerprint = Hash(record), Author = Text(record, "author_id"), Title = Text(record, "title"), Body = Text(record, "body"),
                Parent = OptionalText(record, "parent_id"), Filename = Text(record, "filename") };
            candidates.Add(c);
            if (!record.TryGetProperty("revision", out var revision) || revision.ValueKind != JsonValueKind.Number || !revision.TryGetInt32(out c.Revision) || c.Revision < 1) c.Reasons.Add("invalid_revision");
            if (record.TryGetProperty("deleted", out var deleted))
            {
                if (deleted.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) c.Reasons.Add("invalid_deleted_flag");
                else c.Deleted = deleted.GetBoolean();
            }
            if (!Kinds.Contains(c.Kind)) c.Reasons.Add("unsupported_kind");
            foreach (var name in new[] { "title", "body", "author_id", "original_timestamp", "filename", "kind" })
                if (record.TryGetProperty(name, out var text) && text.ValueKind != JsonValueKind.String) c.Reasons.Add("invalid_text:" + name);
            if (!c.Deleted && c.Kind is "discussion" or "reply" or "decision" && string.IsNullOrWhiteSpace(c.Body)) c.Reasons.Add("missing_body");
            if (c.Title.Length > 180 || c.Body.Length > 20000) c.Reasons.Add("text_exceeds_limit");
            if (!DateTimeOffset.TryParse(Text(record, "original_timestamp"), System.Globalization.CultureInfo.InvariantCulture,
                System.Globalization.DateTimeStyles.None, out c.At)) c.Reasons.Add("invalid_original_timestamp");
            if (!manifest.GetProperty("principals").TryGetProperty(c.Author, out var principal) || principal.ValueKind != JsonValueKind.Object)
                c.Reasons.Add("unresolved_historical_author");
            if (!manifest.GetProperty("studies").TryGetProperty(c.SourceStudyId, out var mapping) || mapping.ValueKind != JsonValueKind.String || mapping.GetString() != study.GroupId
                || !manifest.GetProperty("approved_group_ids").EnumerateArray().Any(g => g.ValueKind == JsonValueKind.String && g.GetString() == study.GroupId))
                c.Reasons.Add("unresolved_or_mismatched_group_mapping");
            if (!ValidAcl(record, study.GroupId)) c.Reasons.Add("unsupported_or_unresolved_acl");
            if (record.TryGetProperty("references", out var references))
            {
                if (references.ValueKind != JsonValueKind.Array || references.GetArrayLength() > 100 || references.EnumerateArray().Any(r => r.ValueKind != JsonValueKind.String || !ValidId(r.GetString())))
                    c.Reasons.Add("invalid_references");
                else c.References = references.EnumerateArray().Select(r => r.GetString()!).ToArray();
            }
            if (!c.Deleted && c.Kind is "version" or "reply" or "attachment" && string.IsNullOrEmpty(c.Parent)) c.Reasons.Add("missing_parent");
            if (c.Parent is not null && !ValidId(c.Parent)) c.Reasons.Add("invalid_parent");
            if (!c.Deleted && c.Kind is "version" or "attachment")
            {
                c.Filename = c.Filename.Length == 0 && c.Kind == "version" ? "synthetic-version.txt" : c.Filename;
                try { c.Bytes = Convert.FromBase64String(Text(record, "content_base64")); }
                catch (FormatException) { c.Reasons.Add("invalid_binary_encoding"); }
                if (c.Bytes is not null)
                {
                    if (!string.Equals(AttachmentStorage.GetHash(c.Bytes), Text(record, "sha256"), StringComparison.OrdinalIgnoreCase)) c.Reasons.Add("checksum_mismatch");
                    if (files.Validate(c.Filename, c.Bytes) is not null) c.Reasons.Add("unsafe_file");
                    else if (files.GetReleaseStatus(c.Filename, c.Bytes) != "DemoReleased") c.Reasons.Add("file_release_quarantine");
                }
                if (c.Kind == "version" && (!record.TryGetProperty("version_number", out var number) || number.ValueKind != JsonValueKind.Number || !number.TryGetInt32(out var v) || v < 1 || v > 100000))
                    c.Reasons.Add("version_number_required");
            }
            if (old is not null)
            {
                if (c.Revision > old.SourceRevision && c.Kind == "decision" && study.Items.FirstOrDefault(i => i.Id == old.TargetId) is { } existingDecision &&
                    DecisionRules.ImportChangeError(study, existingDecision, c.Deleted) is not null) c.Reasons.Add("decision_history_requires_typed_supersession_or_retention");
                if (c.Deleted && c.Revision > old.SourceRevision && c.Kind is "version" or "attachment" && EvidenceRules.ProtectedByAcceptedDocument(study, old.TargetId)) c.Reasons.Add("accepted_document_evidence_cannot_be_removed");
                if (c.Revision > old.SourceRevision && study.CurrentProtocol?.Id == old.TargetId) c.Reasons.Add("current_protocol_must_be_cleared_before_source_change");
                if (old.SourceStudyId != c.SourceStudyId || old.Kind != c.Kind) c.Reasons.Add("immutable_source_identity_changed");
                if (TargetFingerprint(study, old.TargetId, old.Kind) != old.TargetFingerprint) c.Reasons.Add("changed_on_target");
                if (c.Revision < old.SourceRevision) c.Status = "stale_ignored";
                else if (c.Revision == old.SourceRevision)
                {
                    if (c.Fingerprint != old.Fingerprint) c.Reasons.Add("revision_conflict");
                    else c.Status = "unchanged";
                }
                else if (old.Deleted && !c.Deleted) c.Reasons.Add("tombstone_blocks_resurrection");
                else if (!c.Deleted && c.Kind is "version" or "attachment") c.Reasons.Add("immutable_binary_version_changed_use_new_source_id");
            }
            if (c.Status == "imported" && c.Deleted) c.Status = "deleted";
            if (c.Reasons.Count > 0) c.Status = "quarantined";
        }
        var byId = candidates.ToDictionary(c => c.SourceId);
        foreach (var c in candidates.Where(c => c.Status == "imported" && c.Kind == "version"))
        {
            var family = c.Parent is null ? null : byId.GetValueOrDefault(c.Parent)?.TargetId ?? study.ImportLedger.GetValueOrDefault(c.Parent)?.TargetId;
            var ordinal = c.Source.GetProperty("version_number").GetInt32();
            if (study.Files.Any(f => f.FamilyId == family && f.Version == ordinal && f.Id != c.TargetId) ||
                candidates.Any(other => other != c && other.Kind == "version" && !other.Deleted && other.Parent == c.Parent && other.SourceStudyId == c.SourceStudyId &&
                    other.Source.TryGetProperty("version_number", out var n) && n.ValueKind == JsonValueKind.Number && n.TryGetInt32(out var value) && value == ordinal))
            { c.Status = "quarantined"; c.Reasons.Add("duplicate_document_version_number"); }
        }
        // Resolve relationships after all source records are known; propagate quarantine to dependent additions.
        bool changed;
        do
        {
            changed = false;
            foreach (var c in candidates.Where(c => c.Status == "deleted"))
            {
                var childIds = study.Items.Where(i => !i.Deleted && i.ParentId == c.TargetId).Select(i => i.Id)
                    .Concat(study.Files.Where(f => !f.Deleted && (f.ParentId == c.TargetId || f.FamilyId == c.TargetId)).Select(f => f.Id))
                    .Concat(study.ImportLedger.Values.Where(e => !e.Deleted && OptionalText(e.Source.Original, "parent_id") == c.SourceId).Select(e => e.TargetId)).Distinct();
                if (childIds.Any(child => !candidates.Any(other => other.TargetId == child && other.Status == "deleted")))
                { c.Reasons.Add("live_dependents_require_tombstones"); c.Status = "quarantined"; changed = true; }
            }
            foreach (var c in candidates.Where(c => c.Status == "imported"))
            {
                foreach (var reference in c.References.Concat(c.Parent is null ? [] : new[] { c.Parent }))
                {
                    var incoming = byId.GetValueOrDefault(reference);
                    var existing = study.ImportLedger.GetValueOrDefault(reference);
                    var kind = incoming?.Kind ?? existing?.Kind;
                    var sourceStudy = incoming?.SourceStudyId ?? existing?.SourceStudyId;
                    var targetId = incoming?.TargetId ?? existing?.TargetId;
                    var unavailable = incoming is not null ? incoming.Status is "quarantined" or "deleted" || incoming.Deleted
                        : existing is null || existing.Deleted || TargetFingerprint(study, existing.TargetId, existing.Kind) != existing.TargetFingerprint;
                    if (reference == c.SourceId || unavailable || targetId is null) c.Reasons.Add("unavailable_relationship:" + reference);
                    else if ((kind is "version" or "attachment") && (incoming is null || incoming.Status is "unchanged" or "stale_ignored") &&
                        !study.Files.Any(f => f.Id == targetId && EvidenceRules.FileAvailable(study, f.Id, files))) c.Reasons.Add("unavailable_file_relationship:" + reference);
                    else if (sourceStudy != c.SourceStudyId) c.Reasons.Add("cross_study_relationship:" + reference);
                    else if (reference == c.Parent && !AllowedParent(c.Kind, kind)) c.Reasons.Add("invalid_parent_kind:" + reference);
                }
                var seen = new HashSet<string> { c.SourceId };
                var cursor = c.Parent;
                while (cursor is not null)
                {
                    if (!seen.Add(cursor)) { c.Reasons.Add("parent_cycle"); break; }
                    cursor = byId.TryGetValue(cursor, out var parent) ? parent.Parent :
                        study.ImportLedger.TryGetValue(cursor, out var prior) ? OptionalText(prior.Source.Original, "parent_id") : null;
                }
                if (c.Reasons.Count > 0) { c.Status = "quarantined"; changed = true; }
            }
        } while (changed);
        return new(Hash(manifest), candidates);
    }

    static void Apply(Study study, ImportPlan plan, AttachmentStorage files)
    {
        var byId = plan.Candidates.ToDictionary(c => c.SourceId);
        string Target(string source) => byId.TryGetValue(source, out var c) ? c.TargetId : study.ImportLedger[source].TargetId;
        foreach (var c in plan.Candidates.Where(c => c.Status is "imported" or "deleted"))
        {
            study.ImportLedger.TryGetValue(c.SourceId, out var old);
            var original = WithoutBinary(c.Source);
            var source = new SourceProvenance(c.SourceStudyId, c.SourceId, c.Revision, c.Fingerprint,
                c.Deleted ? old?.Source.FamilyId : c.Kind == "version" && c.Parent is not null ? Target(c.Parent) : null,
                c.Deleted ? old?.Source.ReferenceTargetIds ?? [] : c.References.Select(Target).ToArray(), original);
            if (c.Deleted)
            {
                var itemIndex = study.Items.FindIndex(i => i.Id == c.TargetId);
                if (itemIndex >= 0) study.Items[itemIndex] = study.Items[itemIndex] with { Deleted = true, Body = "[Removed from demo view]", Task = null, FileIds = [], Provenance = null };
                var fileIndex = study.Files.FindIndex(f => f.Id == c.TargetId);
                if (fileIndex >= 0) study.Files[fileIndex] = study.Files[fileIndex] with { Deleted = true, Provenance = null };
            }
            else
            {
                var parentId = c.Parent is null ? null : Target(c.Parent);
                var evidence = c.References.Select(Target).FirstOrDefault();
                if (c.Kind is "version" or "attachment")
                {
                    // Bytes are immutable. A source binary change must use a new source version ID.
                    try { files.WriteBlob(c.TargetId, c.Bytes!); }
                    catch (InvalidDataException) { throw new IOException("Immutable import blob integrity conflict."); }
                    var version = c.Kind == "version" ? c.Source.GetProperty("version_number").GetInt32() : 1;
                    var file = new StoredFile(c.TargetId, c.Filename, AttachmentStorage.GetHash(c.Bytes!), c.Bytes!.Length,
                        files.GetReleaseStatus(c.Filename, c.Bytes), c.Kind == "attachment" ? parentId : null, null,
                        c.Kind == "version" ? parentId! : c.TargetId, version, c.Author, c.At) { Provenance = source };
                    study.Files.Add(file);
                }
                if (c.Kind is not ("attachment" or "version"))
                {
                    var kind = c.Kind == "document" ? "documentation" : c.Kind;
                    var fileRefs = c.References.Where(r => (byId.GetValueOrDefault(r)?.Kind ?? study.ImportLedger.GetValueOrDefault(r)?.Kind) is "version" or "attachment").Select(Target).ToArray();
                    var documentId = c.References.Select(Target).FirstOrDefault(r => study.Items.Any(i => i.Id == r && !i.Deleted && i.Kind == "document"));
                    var item = new Item(c.TargetId, kind, string.IsNullOrWhiteSpace(c.Title) ? "Imported synthetic " + c.Kind : c.Title,
                        c.Body.Length == 0 ? "Imported synthetic document family." : c.Body, parentId, documentId,
                        (study.Items.FirstOrDefault(i => i.Id == c.TargetId)?.Version ?? 0) + 1, c.Author, c.At)
                        { Provenance = source, FileIds = fileRefs };
                    var index = study.Items.FindIndex(i => i.Id == c.TargetId);
                    if (index >= 0) study.Items[index] = item; else study.Items.Add(item);
                }
            }
            var history = old?.History.ToList() ?? [];
            if (old is not null) history.Add(old.Source);
            study.ImportLedger[c.SourceId] = new(c.SourceStudyId, c.SourceId, c.Revision, c.Fingerprint, c.TargetId, c.Kind,
                TargetFingerprint(study, c.TargetId, c.Kind), c.Deleted, source, history);
        }
    }

    static ImportReport Report(Study study, ImportPlan plan, string? requestId, bool applied)
    {
        var outcomes = plan.Candidates.Select(c => new ImportOutcome(c.SourceId, c.Status, c.Reasons.Distinct().Order().ToArray(), c.Status == "quarantined" ? null : c.TargetId)).OrderBy(o => o.SourceId).ToList();
        var counts = new[] { "imported", "unchanged", "stale_ignored", "deleted", "quarantined" }.ToDictionary(s => s, s => outcomes.Count(o => o.Status == s));
        return new(applied ? Guid.NewGuid().ToString() : "preview", requestId, DateTimeOffset.UtcNow, applied, study.Revision, outcomes.Count, counts, outcomes, plan.Fingerprint);
    }
    static string TargetFingerprint(Study study, string id, string kind) => Hash(new {
        item = kind is "attachment" or "version" ? null : study.Items.FirstOrDefault(i => i.Id == id),
        file = kind is "version" or "attachment" ? study.Files.FirstOrDefault(f => f.Id == id) : null });
    static bool AllowedParent(string kind, string? parent) => kind switch {
        "version" => parent == "document", "reply" or "attachment" => parent is "discussion" or "reply", _ => parent is not null };
    static IResult Safe(Func<IResult> operation)
    {
        try { return operation(); }
        catch (InvalidDataException) { return Results.BadRequest(new { error = "Invalid synthetic manifest. Use schema 1, unique source IDs, and at most 100 bounded records." }); }
        catch (JsonException) { return Results.BadRequest(new { error = "Invalid synthetic manifest JSON." }); }
        catch (IOException) { return Results.Problem("Import storage is unavailable. Refresh and preview before retrying the same request.", statusCode: 503); }
        catch (UnauthorizedAccessException) { return Results.Problem("Import storage is unavailable.", statusCode: 503); }
    }
    static void ValidateManifest(JsonElement manifest)
    {
        if (manifest.ValueKind != JsonValueKind.Object || Encoding.UTF8.GetByteCount(manifest.GetRawText()) > 900000) throw new InvalidDataException();
        UniqueProperties(manifest);
        if (!manifest.TryGetProperty("schema", out var schema) || schema.ValueKind != JsonValueKind.Number || !schema.TryGetInt32(out var version) || version != 1 ||
            !manifest.TryGetProperty("synthetic", out var synthetic) || synthetic.ValueKind != JsonValueKind.True ||
            !manifest.TryGetProperty("records", out var records) || records.ValueKind != JsonValueKind.Array || records.GetArrayLength() is < 1 or > 100 ||
            !manifest.TryGetProperty("studies", out var studies) || studies.ValueKind != JsonValueKind.Object ||
            !manifest.TryGetProperty("principals", out var principals) || principals.ValueKind != JsonValueKind.Object ||
            !manifest.TryGetProperty("approved_group_ids", out var groups) || groups.ValueKind != JsonValueKind.Array) throw new InvalidDataException();
        var ids = new HashSet<string>();
        foreach (var r in records.EnumerateArray())
            if (r.ValueKind != JsonValueKind.Object || !ValidId(Text(r, "source_id")) || !ValidId(Text(r, "study_id")) || !ids.Add(Text(r, "source_id"))) throw new InvalidDataException();
    }
    static bool ValidAcl(JsonElement record, string group)
    {
        if (!record.TryGetProperty("acl", out var acl) || acl.ValueKind != JsonValueKind.Object || acl.EnumerateObject().Count() != 2 ||
            !acl.TryGetProperty("groups", out var groups) || groups.ValueKind != JsonValueKind.Array || groups.GetArrayLength() != 1 || groups[0].ValueKind != JsonValueKind.String || groups[0].GetString() != group ||
            !acl.TryGetProperty("principals", out var principals) || principals.ValueKind != JsonValueKind.Array || principals.GetArrayLength() != 0) return false;
        return true;
    }
    static bool ValidId(string? id) => id is { Length: > 0 and <= 160 } && id.All(c => char.IsAsciiLetterOrDigit(c) || c is '-' or '_' or '.' or ':');
    static string Text(JsonElement value, string name) => value.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString()! : "";
    static string? OptionalText(JsonElement value, string name) => value.TryGetProperty(name, out var p) && p.ValueKind != JsonValueKind.Null ? Text(value, name) : null;
    static JsonElement WithoutBinary(JsonElement value)
    {
        using var stream = new MemoryStream(); using (var writer = new Utf8JsonWriter(stream)) {
            writer.WriteStartObject(); foreach (var p in value.EnumerateObject().Where(p => p.Name != "content_base64")) { writer.WritePropertyName(p.Name); p.Value.WriteTo(writer); } writer.WriteEndObject(); }
        using var document = JsonDocument.Parse(stream.ToArray()); return document.RootElement.Clone();
    }
    static void UniqueProperties(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object) { var seen = new HashSet<string>(); foreach (var p in value.EnumerateObject()) { if (!seen.Add(p.Name)) throw new InvalidDataException(); UniqueProperties(p.Value); } }
        else if (value.ValueKind == JsonValueKind.Array) foreach (var element in value.EnumerateArray()) UniqueProperties(element);
    }
    static string Hash<T>(T value)
    {
        var element = JsonSerializer.SerializeToElement(value, Json);
        using var stream = new MemoryStream(); using (var writer = new Utf8JsonWriter(stream)) Canonical(writer, element);
        return Convert.ToHexString(SHA256.HashData(stream.ToArray()));
    }
    static void Canonical(Utf8JsonWriter writer, JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object) { writer.WriteStartObject(); foreach (var p in element.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal)) { writer.WritePropertyName(p.Name); Canonical(writer, p.Value); } writer.WriteEndObject(); }
        else if (element.ValueKind == JsonValueKind.Array) { writer.WriteStartArray(); foreach (var v in element.EnumerateArray()) Canonical(writer, v); writer.WriteEndArray(); }
        else element.WriteTo(writer);
    }
}
