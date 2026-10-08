using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;

public record DecisionDetails(string FamilyId, string? SupersedesId, string OwnerId, string EffectiveDate,
    string Alternatives, string Reason, string[] ItemIds, string[] FileIds);
public record DecisionCaptureState(string Status, string FamilyId, string? SupersedesId, string? SupersededById);
public record DecisionWriteInput(string Title, string Rationale, string? Alternatives, string OwnerId,
    string EffectiveDate, string[]? ItemIds, string[]? FileIds, string? Reason, int ExpectedRevision, string RequestId);

public static class DecisionRules
{
    public static string Family(Item item) => item.Decision?.FamilyId ?? item.Id;
    public static DecisionCaptureState CaptureState(Study study, Item item)
    {
        // Retained successor links remain authoritative even if a malformed historical store marks a successor deleted.
        var successor = study.Items.FirstOrDefault(i => i.Kind == "decision" && i.Decision?.SupersedesId == item.Id);
        return new(successor is null ? "Current" : "Superseded", Family(item), item.Decision?.SupersedesId, successor?.Id);
    }
    public static IEnumerable<string> References(Item item) => (item.ParentId is null ? [] : new[] { item.ParentId })
        .Concat(item.DocumentId is null ? [] : new[] { item.DocumentId }).Concat(item.Task?.Links ?? [])
        .Concat(item.Provenance?.ReferenceTargetIds ?? []).Concat(item.Decision?.ItemIds ?? [])
        .Concat(item.BoardDecision is null ? [] : new[] { item.BoardDecision.IdeaVersionId });
    public static string? DeletionError(Study study, Item item)
    {
        if (item.Kind != "decision") return null;
        if (item.Decision?.SupersedesId is not null || study.Items.Any(i => i.Kind == "decision" && i.Decision?.SupersedesId == item.Id))
            return "Superseded decisions and their replacements are retained as an immutable decision trail.";
        if (study.Items.Any(i => !i.Deleted && i.Id != item.Id && References(i).Contains(item.Id)) ||
            study.Files.Any(f => !f.Deleted && (f.ParentId == item.Id || f.DocumentId == item.Id || f.FamilyId == item.Id ||
                (f.Provenance?.ReferenceTargetIds.Contains(item.Id) ?? false))))
            return "This exact decision is referenced by live study content and cannot be removed.";
        return null;
    }
    public static string? ImportChangeError(Study study, Item item, bool deleting) => item.Kind != "decision" ? null : deleting
        ? DeletionError(study, item)
        : "Existing decision rationale is immutable. Use a distinct source record or the typed supersession workflow.";
}

public static class DecisionEndpoints
{
    static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    public static void MapDecisionEndpoints(this WebApplication app, Func<HttpContext, string> identity,
        Func<State, string, Study, bool> access)
    {
        app.MapGet("/api/studies/{id}/decisions", (string id, HttpContext context, IStudyStore store) => store.Read<IResult>(state => {
            var actor = identity(context);
            var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, actor, s));
            if (study is null) return Results.NotFound();
            var decisions = study.Items.Where(i => i.Kind == "decision" && EvidenceRules.ItemAvailable(study, i.Id)).ToArray();
            return Results.Ok(new { studyRole = DocumentRules.StudyRole(actor), studyRevision = study.Revision,
                current = decisions.Where(i => DecisionRules.CaptureState(study, i).Status == "Current").Select(i => Entry(study, i)),
                history = decisions.Where(i => DecisionRules.CaptureState(study, i).Status == "Superseded").Select(i => Entry(study, i)) });
        }));
        app.MapGet("/api/studies/{id}/decisions/{decisionId}", (string id, string decisionId, HttpContext context, IStudyStore store) => store.Read<IResult>(state => {
            var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, identity(context), s));
            var item = study?.Items.FirstOrDefault(i => i.Id == decisionId && i.Kind == "decision" && EvidenceRules.ItemAvailable(study!, i.Id));
            return item is null ? Results.NotFound() : Results.Ok(Detail(study!, item));
        }));
        app.MapPost("/api/studies/{id}/decisions", (string id, DecisionWriteInput input, HttpContext context, IStudyStore store, AttachmentStorage storage) =>
            Write(id, null, input, context, store, storage, identity, access));
        app.MapPost("/api/studies/{id}/decisions/{decisionId}/supersede", (string id, string decisionId, DecisionWriteInput input, HttpContext context, IStudyStore store, AttachmentStorage storage) =>
            Write(id, decisionId, input, context, store, storage, identity, access));
    }

    static IResult Write(string id, string? previousId, DecisionWriteInput input, HttpContext context, IStudyStore store,
        AttachmentStorage storage, Func<HttpContext, string> identity, Func<State, string, Study, bool> access) => store.Change(state => {
            var actor = identity(context);
            var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, actor, s));
            if (study is null) return Results.NotFound();
            var role = DocumentRules.StudyRole(actor);
            if (role is not ("Researcher" or "Reviewer" or "StudyLead") || previousId is not null && role is not ("Reviewer" or "StudyLead"))
                return Results.StatusCode(403);
            if (!Guid.TryParse(input.RequestId, out _) || input.ExpectedRevision < 1 || string.IsNullOrWhiteSpace(input.Title) || input.Title.Length > 180 ||
                string.IsNullOrWhiteSpace(input.Rationale) || input.Rationale.Length > 20000 || input.Alternatives?.Length > 4000 || input.Reason?.Length > 1000 ||
                previousId is not null && string.IsNullOrWhiteSpace(input.Reason) || string.IsNullOrWhiteSpace(input.OwnerId) ||
                !DateOnly.TryParseExact(input.EffectiveDate, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var date) || date.Year is < 1900 or > 2100 ||
                !ValidIds(input.ItemIds) || !ValidIds(input.FileIds))
                return Results.BadRequest(new { error = "Provide title (1–180), rationale (1–20000), alternatives (0–4000), a current-member owner, YYYY-MM-DD date (1900–2100), up to 30 distinct item/file IDs, and a request identifier. Supersession requires a reason (1–1000)." });
            var fingerprint = Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(new { operation = "decision", previousId, input }, Json)));
            if (study.Requests.TryGetValue(input.RequestId, out var prior))
            {
                if (prior != fingerprint || !study.DecisionRequests.TryGetValue(input.RequestId, out var createdId))
                    return Results.Conflict(new { error = "Request identifier belongs to another operation." });
                var created = study.Items.FirstOrDefault(i => i.Id == createdId && i.Kind == "decision" && EvidenceRules.ItemAvailable(study, i.Id));
                return created is null ? Results.NotFound() : Results.Ok(Detail(study, created));
            }
            if (study.Stage != "Active" || study.Revision != input.ExpectedRevision)
                return Results.Conflict(new { error = "Refresh the active study before recording a decision." });
            var previous = previousId is null ? null : study.Items.FirstOrDefault(i => i.Id == previousId && i.Kind == "decision" && EvidenceRules.ItemAvailable(study, i.Id));
            if (previousId is not null && previous is null) return Results.NotFound();
            if (previous is not null && study.Items.Any(i => i.Kind == "decision" && i.Decision?.SupersedesId == previous.Id))
                return Results.Conflict(new { error = "That decision already has a replacement. Supersede its current successor to continue the single decision trail." });
            if (!Demo.Identities.Any(i => i.Id == input.OwnerId) || !Demo.Groups.GetValueOrDefault(input.OwnerId, []).Contains(study.GroupId))
                return Results.BadRequest(new { error = "The responsible owner must currently belong to this study's authoritative group. Assignment does not grant access." });
            var itemIds = input.ItemIds ?? [];
            var fileIds = input.FileIds ?? [];
            if (itemIds.Any(itemId => !EvidenceRules.ItemAvailable(study, itemId)) ||
                fileIds.Any(fileId => !EvidenceRules.FileAvailable(study, fileId, storage)))
                return Results.BadRequest(new { error = "Evidence must reference exact live records and released, integrity-verified file versions in this study." });
            if (itemIds.Any(itemId => study.Items.Any(i => i.Id == itemId && i.BoardIdea is not null)))
                return Results.BadRequest(new { error = "Convert a brainstorming idea through its session to preserve exact-version and reverse decision links." });
            var now = DateTimeOffset.UtcNow;
            var newId = Guid.NewGuid().ToString();
            var details = new DecisionDetails(previous is null ? newId : DecisionRules.Family(previous), previous?.Id,
                input.OwnerId, input.EffectiveDate, input.Alternatives?.Trim() ?? "", input.Reason?.Trim() ?? "", itemIds.ToArray(), fileIds.ToArray());
            var decision = new Item(newId, "decision", input.Title.Trim(), input.Rationale, previous?.Id, null,
                previous is null ? 1 : checked(previous.Version + 1), actor, now) {
                Decision = details, FileIds = fileIds.ToArray(), BoardDecision = previous?.BoardDecision };
            study.Items.Add(decision);
            study.DecisionRequests.Add(input.RequestId, decision.Id);
            study.Requests.Add(input.RequestId, fingerprint);
            study.Revision++;
            state.Audit.Add(new(actor, previous is null ? "Recorded immutable decision" : "Superseded decision " + previous.Id + " with " + decision.Id, study.Id, now));
            return Results.Ok(Detail(study, decision));
        });

    static bool ValidIds(string[]? ids) => ids is null || ids.Length <= 30 && ids.Distinct(StringComparer.Ordinal).Count() == ids.Length &&
        ids.All(id => !string.IsNullOrWhiteSpace(id) && id.Length <= 160);
    static object Entry(Study study, Item item)
    {
        var state = DecisionRules.CaptureState(study, item);
        return new { item, state.Status, state.FamilyId, state.SupersedesId, state.SupersededById };
    }
    static object Detail(Study study, Item item)
    {
        var state = DecisionRules.CaptureState(study, item);
        return new { item, state.Status, state.FamilyId, state.SupersedesId, state.SupersededById,
            lineage = study.Items.Where(i => i.Kind == "decision" && EvidenceRules.ItemAvailable(study, i.Id) && DecisionRules.Family(i) == state.FamilyId)
                .OrderBy(i => i.Version).ThenBy(i => i.CreatedAt).Select(i => Entry(study, i)) };
    }
}
