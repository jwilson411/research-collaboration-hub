using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

public record BrainstormIdeaVersion(string BoardId, string IdeaId, string? PreviousVersionId);
public record BrainstormDecisionSource(string BoardId, string IdeaId, string IdeaVersionId, int IdeaVersion,
    string SourceAuthor, DateTimeOffset SourceCreatedAt);
public record BrainstormSessionState(string Title, string Purpose, string ResponsibleId, string Status,
    List<string> IdeaOrder, Dictionary<string, string> CurrentVersions);
public record BrainstormEvent(string Action, string Actor, DateTimeOffset At, string Reason,
    BrainstormSessionState? Before = null, BrainstormSessionState? After = null);
public record BrainstormOperation(string? DecisionId);
public sealed class BrainstormBoard
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string Purpose { get; set; } = "";
    public string ResponsibleId { get; set; } = "";
    public string Status { get; set; } = "Active";
    public string CreatedBy { get; set; } = "";
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }
    public List<string> IdeaOrder { get; set; } = [];
    public Dictionary<string, string> CurrentVersions { get; set; } = [];
    public List<BrainstormEvent> History { get; set; } = [];
    public Dictionary<string, BrainstormOperation> Operations { get; set; } = [];
}
public record BoardInput(string Title, string Purpose, string ResponsibleId, int ExpectedRevision, string RequestId);
public record BoardStateInput(string Status, string Reason, int ExpectedRevision, string RequestId);
public record BoardIdeaInput(string Title, string Body, int ExpectedRevision, string RequestId);
public record BoardRevisionInput(int ExpectedRevision, string RequestId);
public record BoardOrderInput(string[]? IdeaIds, int ExpectedRevision, string RequestId);
public record BoardDecisionInput(string VersionId, string Title, string Rationale, int ExpectedRevision, string RequestId);

public static class BoardEndpoints
{
    static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    sealed record Mutation(BrainstormBoard Board, string Action, string Reason, string? DecisionId = null);
    sealed class Rejected(int status, string message) : Exception(message) { public int Status = status; }

    public static void MapBoardEndpoints(this WebApplication app, Func<HttpContext, string> identity,
        Func<State, string, Study, bool> access)
    {
        app.MapGet("/api/studies/{id}/boards", (string id, HttpContext context, IStudyStore store) => store.Read<IResult>(state => {
            var actor = identity(context);
            var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, actor, s));
            return study is null ? Results.NotFound() : Results.Ok(new {
                studyRole = DocumentRules.StudyRole(actor), studyRevision = study.Revision,
                boards = study.Boards.Select(b => new { b.Id, b.Title, b.Purpose, b.ResponsibleId, b.Status,
                    ideaCount = b.IdeaOrder.Count, b.CreatedBy, b.CreatedAt, b.UpdatedAt }) });
        }));
        app.MapGet("/api/studies/{id}/boards/{boardId}", (string id, string boardId, HttpContext context, IStudyStore store) => store.Read<IResult>(state => {
            var actor = identity(context);
            var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, actor, s));
            var board = study?.Boards.FirstOrDefault(b => b.Id == boardId);
            return board is null ? Results.NotFound() : Results.Ok(Project(study!, board, actor));
        }));
        app.MapGet("/api/studies/{id}/boards/{boardId}/export", (string id, string boardId, HttpContext context, IStudyStore store) => store.Read<IResult>(state => {
            var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, identity(context), s));
            var board = study?.Boards.FirstOrDefault(b => b.Id == boardId);
            if (board is null) return Results.NotFound();
            var text = new StringBuilder("Synthetic brainstorming session — readable export\n");
            text.AppendLine("Title: " + board.Title).AppendLine("Purpose: " + board.Purpose)
                .AppendLine("Responsible: " + board.ResponsibleId).AppendLine("Session state: " + board.Status)
                .AppendLine("Study revision: " + study!.Revision).AppendLine("This export is coordination context, not an approval.");
            foreach (var ideaId in board.IdeaOrder)
            {
                var versions = Versions(study, board.Id, ideaId);
                foreach (var version in versions)
                {
                    text.AppendLine().AppendLine($"Idea {ideaId} — exact version {version.Version} ({version.Id})")
                        .AppendLine(version.Title).AppendLine(version.Body)
                        .AppendLine($"Author: {version.Author}; recorded: {version.CreatedAt:O}");
                    foreach (var decision in Decisions(study, version.Id))
                        {
                        var disposition = DecisionRules.CaptureState(study, decision);
                        text.AppendLine("Linked decision: " + decision.Id + " — " + decision.Title + " [" + disposition.Status + "]"
                            + (disposition.SupersededById is null ? "" : "; replacement: " + disposition.SupersededById));
                    }
                }
            }
            return Results.File(Encoding.UTF8.GetBytes(text.ToString()), "text/plain; charset=utf-8", "brainstorm-" + board.Id + ".txt");
        }));
        app.MapPost("/api/studies/{id}/boards", (string id, BoardInput input, HttpContext context, IStudyStore store) =>
            Change(id, null, "create", input, input.ExpectedRevision, input.RequestId, false, false, context, store, identity, access,
                (study, _, actor) => {
                    ValidateMetadata(study, input);
                    if (study.Boards.Count >= 50) throw new Rejected(409, "This synthetic study has reached its 50-session limit.");
                    var now = DateTimeOffset.UtcNow;
                    var board = new BrainstormBoard { Id = Guid.NewGuid().ToString(), Title = input.Title.Trim(), Purpose = input.Purpose.Trim(),
                        ResponsibleId = input.ResponsibleId, CreatedBy = actor, CreatedAt = now, UpdatedAt = now };
                    study.Boards.Add(board);
                    return new(board, "Created session", "Synthetic brainstorming session created.");
                }));
        app.MapPost("/api/studies/{id}/boards/{boardId}", (string id, string boardId, BoardInput input, HttpContext context, IStudyStore store) =>
            Change(id, boardId, "metadata", input, input.ExpectedRevision, input.RequestId, true, false, context, store, identity, access,
                (study, board, _) => {
                    ValidateMetadata(study, input);
                    board!.Title = input.Title.Trim(); board.Purpose = input.Purpose.Trim(); board.ResponsibleId = input.ResponsibleId;
                    return new(board, "Updated session", "Updated title, purpose and responsible participant.");
                }));
        app.MapPost("/api/studies/{id}/boards/{boardId}/state", (string id, string boardId, BoardStateInput input, HttpContext context, IStudyStore store) =>
            Change(id, boardId, "state", input, input.ExpectedRevision, input.RequestId, false, true, context, store, identity, access,
                (_, board, _) => {
                    if (input.Status is not ("Active" or "Archived") || string.IsNullOrWhiteSpace(input.Reason) || input.Reason.Length > 1000)
                        throw new Rejected(400, "Choose Active or Archived and give a reason of 1–1000 characters.");
                    if (board!.Status == input.Status) throw new Rejected(409, "The session is already in that state.");
                    board.Status = input.Status;
                    return new(board, input.Status == "Active" ? "Reopened session" : "Archived session", input.Reason.Trim());
                }));
        app.MapPost("/api/studies/{id}/boards/{boardId}/ideas", (string id, string boardId, BoardIdeaInput input, HttpContext context, IStudyStore store) =>
            Change(id, boardId, "idea-create", input, input.ExpectedRevision, input.RequestId, true, false, context, store, identity, access,
                (study, board, actor) => {
                    ValidateIdea(input.Title, input.Body);
                    if (board!.IdeaOrder.Count >= 100) throw new Rejected(409, "This synthetic session has reached its 100-idea limit.");
                    var ideaId = Guid.NewGuid().ToString();
                    var item = new Item(Guid.NewGuid().ToString(), "idea", input.Title.Trim(), input.Body, null, null, 1, actor, DateTimeOffset.UtcNow)
                        { BoardIdea = new(board.Id, ideaId, null) };
                    study.Items.Add(item); board.IdeaOrder.Add(ideaId); board.CurrentVersions.Add(ideaId, item.Id);
                    return new(board, "Added idea", "Added a first immutable idea version.");
                }));
        app.MapPost("/api/studies/{id}/boards/{boardId}/ideas/{ideaId}/versions", (string id, string boardId, string ideaId, BoardIdeaInput input, HttpContext context, IStudyStore store) =>
            Change(id, boardId, "idea-revise:" + ideaId, input, input.ExpectedRevision, input.RequestId, true, false, context, store, identity, access,
                (study, board, actor) => {
                    ValidateIdea(input.Title, input.Body);
                    var previous = Current(study, board!, ideaId);
                    if (previous.Version >= 100) throw new Rejected(409, "This synthetic idea has reached its 100-version limit.");
                    var item = new Item(Guid.NewGuid().ToString(), "idea", input.Title.Trim(), input.Body, null, null, previous.Version + 1, actor, DateTimeOffset.UtcNow)
                        { BoardIdea = new(board!.Id, ideaId, previous.Id) };
                    study.Items.Add(item); board.CurrentVersions[ideaId] = item.Id;
                    return new(board, "Revised idea", "Retained the prior version and recorded a new immutable version.");
                }));
        app.MapPost("/api/studies/{id}/boards/{boardId}/reorder", (string id, string boardId, BoardOrderInput input, HttpContext context, IStudyStore store) =>
            Change(id, boardId, "reorder", input, input.ExpectedRevision, input.RequestId, true, false, context, store, identity, access,
                (_, board, _) => {
                    if (input.IdeaIds is null || input.IdeaIds.Length != board!.IdeaOrder.Count ||
                        input.IdeaIds.Any(string.IsNullOrWhiteSpace) || input.IdeaIds.Distinct().Count() != input.IdeaIds.Length ||
                        !input.IdeaIds.ToHashSet(StringComparer.Ordinal).SetEquals(board.IdeaOrder))
                        throw new Rejected(400, "Provide each current idea ID exactly once, in the desired order.");
                    board.IdeaOrder = input.IdeaIds.ToList();
                    return new(board, "Reordered ideas", "Changed the accessible idea list order.");
                }));
        app.MapPost("/api/studies/{id}/boards/{boardId}/ideas/{ideaId}/decisions", (string id, string boardId, string ideaId, BoardDecisionInput input, HttpContext context, IStudyStore store) =>
            Change(id, boardId, "decision:" + ideaId, input, input.ExpectedRevision, input.RequestId, true, false, context, store, identity, access,
                (study, board, actor) => {
                    ValidateIdea(input.Title, input.Rationale);
                    Current(study, board!, ideaId);
                    var version = Versions(study, board!.Id, ideaId).FirstOrDefault(i => i.Id == input.VersionId)
                        ?? throw new Rejected(404, "That exact idea version is unavailable in this session.");
                    var decision = new Item(Guid.NewGuid().ToString(), "decision", input.Title.Trim(), input.Rationale, version.Id, null, 1, actor, DateTimeOffset.UtcNow)
                        { BoardDecision = new(board.Id, ideaId, version.Id, version.Version, version.Author, version.CreatedAt) };
                    study.Items.Add(decision);
                    return new(board, "Recorded linked decision", "Linked a decision to an exact retained idea version.", decision.Id);
                }));
        app.MapPost("/api/studies/{id}/boards/{boardId}/ideas/{ideaId}/delete", (string id, string boardId, string ideaId, BoardRevisionInput input, HttpContext context, IStudyStore store) =>
            Change(id, boardId, "idea-delete:" + ideaId, input, input.ExpectedRevision, input.RequestId, true, false, context, store, identity, access,
                (study, board, _) => {
                    Current(study, board!, ideaId);
                    var versions = Versions(study, board!.Id, ideaId).Select(i => i.Id).ToHashSet(StringComparer.Ordinal);
                    if (study.Items.Any(i => !i.Deleted && !versions.Contains(i.Id) && References(i).Any(versions.Contains)) ||
                        study.Files.Any(f => !f.Deleted && ((f.ParentId is not null && versions.Contains(f.ParentId)) ||
                            (f.DocumentId is not null && versions.Contains(f.DocumentId)) || versions.Contains(f.FamilyId) ||
                            (f.Provenance?.ReferenceTargetIds.Any(versions.Contains) ?? false))))
                        throw new Rejected(409, "This idea has a version referenced by live study content. Preserve its decision or evidence trail.");
                    for (var index = 0; index < study.Items.Count; index++)
                        if (versions.Contains(study.Items[index].Id)) study.Items[index] = study.Items[index] with {
                            Title = "Removed brainstorming idea", Body = "[Removed from demo view]", Deleted = true,
                            Task = null, FileIds = [], Provenance = null, BoardDecision = null };
                    board.IdeaOrder.Remove(ideaId); board.CurrentVersions.Remove(ideaId);
                    return new(board, "Removed unreferenced idea", "Removed all versions of an unreferenced idea from current access.");
                }));
    }

    static IResult Change<T>(string studyId, string? boardId, string operation, T input, int expectedRevision, string requestId,
        bool activeBoard, bool reviewerOnly, HttpContext context, IStudyStore store, Func<HttpContext, string> identity,
        Func<State, string, Study, bool> access, Func<Study, BrainstormBoard?, string, Mutation> mutate) => store.Change(state => {
            var actor = identity(context);
            var study = state.Studies.FirstOrDefault(s => s.Id == studyId && access(state, actor, s));
            if (study is null) return Results.NotFound();
            var role = DocumentRules.StudyRole(actor);
            if (role is not ("Researcher" or "Reviewer" or "StudyLead") || reviewerOnly && role is not ("Reviewer" or "StudyLead"))
                return Results.StatusCode(403);
            var board = boardId is null ? null : study.Boards.FirstOrDefault(b => b.Id == boardId);
            if (boardId is not null && board is null) return Results.NotFound();
            if (!Guid.TryParse(requestId, out _) || expectedRevision < 1) return Results.BadRequest(new { error = "Provide a study revision and request identifier." });
            var fingerprint = Convert.ToHexString(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(new { operation = "board:" + operation, boardId, input }, Json)));
            if (study.Requests.TryGetValue(requestId, out var prior))
            {
                var savedBoard = study.Boards.FirstOrDefault(b => b.Operations.ContainsKey(requestId));
                return prior == fingerprint && savedBoard is not null
                    ? Results.Ok(Project(study, savedBoard, actor, savedBoard.Operations[requestId].DecisionId))
                    : Results.Conflict(new { error = "Request identifier belongs to another operation." });
            }
            if (study.Revision != expectedRevision || study.Stage != "Active")
                return Results.Conflict(new { error = "Refresh the active study before changing this session." });
            if (activeBoard && board?.Status != "Active") return Results.Conflict(new { error = "Reopen the brainstorming session before changing its content." });
            if (board?.History.Count >= 1000) return Results.Conflict(new { error = "This synthetic session has reached its change-history limit." });
            try
            {
                var before = board is null ? null : SessionState(board);
                var changed = mutate(study, board, actor);
                var now = DateTimeOffset.UtcNow;
                changed.Board.UpdatedAt = now;
                changed.Board.History.Add(new(changed.Action, actor, now, changed.Reason, before, SessionState(changed.Board)));
                changed.Board.Operations.Add(requestId, new(changed.DecisionId));
                study.Requests.Add(requestId, fingerprint);
                study.Revision++;
                state.Audit.Add(new(actor, changed.Action + " in brainstorming session " + changed.Board.Id, study.Id, now));
                return Results.Ok(Project(study, changed.Board, actor, changed.DecisionId));
            }
            catch (Rejected rejected) { return Results.Json(new { error = rejected.Message }, statusCode: rejected.Status); }
        });

    static BrainstormSessionState SessionState(BrainstormBoard board) => new(board.Title, board.Purpose,
        board.ResponsibleId, board.Status, board.IdeaOrder.ToList(), board.CurrentVersions.ToDictionary(pair => pair.Key, pair => pair.Value));
    static object Project(Study study, BrainstormBoard board, string actor, string? decisionId = null) => new {
        board.Id, board.Title, board.Purpose, board.ResponsibleId, board.Status, board.CreatedBy, board.CreatedAt, board.UpdatedAt,
        responsibleAvailable = Demo.Groups.GetValueOrDefault(board.ResponsibleId, []).Contains(study.GroupId),
        studyRevision = study.Revision, studyRole = DocumentRules.StudyRole(actor), ideaOrder = board.IdeaOrder,
        ideas = board.IdeaOrder.Select(ideaId => new {
            id = ideaId, currentVersionId = board.CurrentVersions.GetValueOrDefault(ideaId),
            current = study.Items.FirstOrDefault(i => i.Id == board.CurrentVersions.GetValueOrDefault(ideaId) && !i.Deleted),
            versions = Versions(study, board.Id, ideaId).Select(i => new { item = i, decisions = Decisions(study, i.Id).Select(d => new { d.Id, d.Title, status = DecisionRules.CaptureState(study, d).Status, supersededById = DecisionRules.CaptureState(study, d).SupersededById }) }) }),
        history = board.History, decisionId = decisionId is not null && study.Items.Any(i => i.Id == decisionId && !i.Deleted) ? decisionId : null };
    static List<Item> Versions(Study study, string boardId, string ideaId) => study.Items
        .Where(i => !i.Deleted && i.BoardIdea is { } version && version.BoardId == boardId && version.IdeaId == ideaId)
        .OrderBy(i => i.Version).ToList();
    static IEnumerable<Item> Decisions(Study study, string versionId) => study.Items.Where(i => !i.Deleted && i.BoardDecision?.IdeaVersionId == versionId);
    static Item Current(Study study, BrainstormBoard board, string ideaId) => board.CurrentVersions.TryGetValue(ideaId, out var versionId)
        ? study.Items.FirstOrDefault(i => i.Id == versionId && !i.Deleted && i.BoardIdea?.BoardId == board.Id && i.BoardIdea.IdeaId == ideaId)
            ?? throw new Rejected(404, "Idea is unavailable in this session.")
        : throw new Rejected(404, "Idea is unavailable in this session.");
    static IEnumerable<string> References(Item item) => (item.ParentId is null ? [] : new[] { item.ParentId })
        .Concat(item.DocumentId is null ? [] : new[] { item.DocumentId }).Concat(item.Task?.Links ?? [])
        .Concat(item.Provenance?.ReferenceTargetIds ?? []).Concat(item.Decision?.ItemIds ?? []).Concat(item.BoardDecision is null ? [] : new[] { item.BoardDecision.IdeaVersionId });
    static void ValidateMetadata(Study study, BoardInput input)
    {
        if (string.IsNullOrWhiteSpace(input.Title) || input.Title.Length > 180 || string.IsNullOrWhiteSpace(input.Purpose) || input.Purpose.Length > 4000 ||
            string.IsNullOrWhiteSpace(input.ResponsibleId) || !Demo.Identities.Any(i => i.Id == input.ResponsibleId) ||
            !Demo.Groups.GetValueOrDefault(input.ResponsibleId, []).Contains(study.GroupId))
            throw new Rejected(400, "Provide title (1–180), purpose (1–4000), and a responsible participant currently in this study's group. Assignment never grants access.");
    }
    static void ValidateIdea(string title, string body)
    {
        if (string.IsNullOrWhiteSpace(title) || title.Length > 180 || string.IsNullOrWhiteSpace(body) || body.Length > 20000)
            throw new Rejected(400, "Provide an idea/decision title (1–180) and text (1–20000).");
    }
}
