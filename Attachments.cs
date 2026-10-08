using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

// The policy is intentionally not an antivirus implementation. Replace with an approved
// scanner/quarantine workflow before allowing any production release.
public interface IAttachmentReleasePolicy
{
    string Evaluate(string extension, byte[] content);
}
public sealed class SyntheticAttachmentPolicy(bool releaseText) : IAttachmentReleasePolicy
{
    public string Evaluate(string extension, byte[] content) =>
        releaseText && (extension == ".txt" || (extension == ".png" &&
            Convert.ToHexString(SHA256.HashData(content)) == "5E3D382DB4DD83D59AA5742793AD6B7903409E865C83BCBC54835049F043BC15"))
            ? "DemoReleased" : "Quarantined";
}
public record StoredFile(string Id, string Name, string Sha256, long Size, string Status,
    string? ParentId, string? DocumentId, string FamilyId, int Version, string Author,
    DateTimeOffset CreatedAt, bool Deleted = false);
public record AttachmentInput(string Name, string ContentBase64, string? ParentId,
    string? DocumentId, int ExpectedRevision, string RequestId);
public record AttachmentRevisionInput(int ExpectedRevision, string RequestId);

public static class AttachmentEndpoints
{
    const int MaxBytes = 512 * 1024;
    static readonly UTF8Encoding StrictUtf8 = new(false, true);
    public static void MapAttachmentEndpoints(this WebApplication app,
        Func<HttpContext, string> identity, Func<State, string, Study, bool> access)
    {
        var root = Path.GetFullPath(Environment.GetEnvironmentVariable("HUB_FILES") ??
            Path.Combine(Directory.GetParent(app.Environment.ContentRootPath)!.FullName, ".hub-files"));
        var contentRoot = Path.GetFullPath(app.Environment.ContentRootPath);
        if (IsWithin(root, contentRoot) || IsWithin(contentRoot, root))
            throw new InvalidOperationException("Attachment storage must be outside the application content root, in a dedicated directory.");
        // Refuse symlinked roots and ancestors: a lexical outside-root check alone is insufficient.
        for (DirectoryInfo? directory = new(root); directory is not null; directory = directory.Parent)
            if (directory.LinkTarget is not null)
                throw new InvalidOperationException("Attachment storage must not use symlinked directories.");
        Directory.CreateDirectory(root);
        var policy = new SyntheticAttachmentPolicy(app.Environment.IsDevelopment() &&
            Environment.GetEnvironmentVariable("HUB_DEMO_FILE_RELEASE") == "true");

        app.MapGet("/api/studies/{id}/files", (string id, HttpContext context, IStudyStore store) =>
            store.Read<IResult>(state =>
            {
                var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, identity(context), s));
                return study is null ? Results.NotFound() : Results.Ok(study.Files.Where(f => Visible(study, f)));
            }));

        app.MapPost("/api/studies/{id}/files", (string id, AttachmentInput input, HttpContext context, IStudyStore store) =>
            WithStorageErrors(() => store.Change(state =>
            {
                // Authorize before base64 decoding, signature processing, or filesystem writes.
                var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, identity(context), s));
                if (study is null) return Results.NotFound();
                if (!Guid.TryParse(input.RequestId, out _) || !ValidName(input.Name) ||
                    string.IsNullOrEmpty(input.ContentBase64) || input.ContentBase64.Length > ((MaxBytes + 2) / 3) * 4)
                    return Results.BadRequest(new { error = "Use a safe filename and a nonempty file of at most 512 KiB." });
                var fingerprint = Fingerprint("file-upload", input);
                if (study.Requests.TryGetValue(input.RequestId, out var previous))
                    return previous == fingerprint ? Results.Ok(study) : Results.Conflict(new { error = "Request identifier was used for another operation." });
                if (study.Revision != input.ExpectedRevision || study.Stage != "Active")
                    return Results.Conflict(new { error = "Refresh the active study before uploading." });
                if (input.ParentId is not null && !study.Items.Any(i => i.Id == input.ParentId && !i.Deleted && i.Kind is "discussion" or "reply"))
                    return Results.BadRequest(new { error = "Attachment parent must be a live discussion or reply in this study." });
                var prior = input.DocumentId is null ? null : study.Files.FirstOrDefault(f => f.Id == input.DocumentId && Visible(study, f));
                if (input.DocumentId is not null && prior is null)
                    return Results.BadRequest(new { error = "A prior version must be a live file in this study." });
                if (prior is not null && prior.ParentId != input.ParentId)
                    return Results.BadRequest(new { error = "A new file version must retain its discussion relationship." });
                byte[] bytes;
                try { bytes = Convert.FromBase64String(input.ContentBase64); }
                catch (FormatException) { return Results.BadRequest(new { error = "File content must be valid base64." }); }
                var extension = Path.GetExtension(input.Name).ToLowerInvariant();
                if (bytes.Length == 0 || bytes.Length > MaxBytes || !ValidContent(extension, bytes))
                    return Results.BadRequest(new { error = "File signature or text encoding does not match an allowed .txt, .pdf, .png, or .jpg file." });
                var fileId = Guid.NewGuid().ToString("N");
                var file = new StoredFile(fileId, input.Name, Convert.ToHexString(SHA256.HashData(bytes)), bytes.Length,
                    policy.Evaluate(extension, bytes), input.ParentId, input.DocumentId, prior?.FamilyId ?? fileId,
                    prior is null ? 1 : study.Files.Where(f => f.FamilyId == prior.FamilyId).Max(f => f.Version) + 1,
                    identity(context), DateTimeOffset.UtcNow);
                // Immutable generated filename; never use user filename in a filesystem path.
                // A crash before metadata commit leaves only an inaccessible orphan blob.
                using (var stream = new FileStream(BlobPath(root, fileId), FileMode.CreateNew, FileAccess.Write, FileShare.None))
                { stream.Write(bytes); stream.Flush(true); }
                study.Files.Add(file);
                study.Revision++;
                study.Requests.Add(input.RequestId, fingerprint);
                state.Audit.Add(new(identity(context), "Uploaded file: " + file.Status, study.Id, DateTimeOffset.UtcNow));
                return Results.Ok(study);
            })));

        app.MapGet("/api/studies/{id}/files/{fileId}/download", (string id, string fileId, HttpContext context, IStudyStore store) =>
            WithStorageErrors(() => store.Read<IResult>(state =>
            {
                var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, identity(context), s));
                var file = study?.Files.FirstOrDefault(f => f.Id == fileId && Visible(study, f));
                if (file is null) return Results.NotFound();
                if (file.Status != "DemoReleased")
                    return Results.Conflict(new { error = "File remains quarantined. No approved malware scanner is configured." });
                var path = BlobPath(root, file.Id);
                if (!File.Exists(path) || new FileInfo(path).LinkTarget is not null)
                    return Results.NotFound();
                var info = new FileInfo(path);
                if (info.Length != file.Size || info.Length > MaxBytes) return Results.Conflict(new { error = "Stored file integrity check failed." });
                var bytes = File.ReadAllBytes(path);
                if (Convert.ToHexString(SHA256.HashData(bytes)) != file.Sha256)
                    return Results.Conflict(new { error = "Stored file integrity check failed." });
                if (policy.Evaluate(Path.GetExtension(file.Name).ToLowerInvariant(), bytes) != "DemoReleased")
                    return Results.Conflict(new { error = "Synthetic release policy is disabled; download remains quarantined." });
                return Results.File(bytes, "application/octet-stream", file.Name, enableRangeProcessing: false);
            })));

        app.MapPost("/api/studies/{id}/files/{fileId}/delete", (string id, string fileId, AttachmentRevisionInput input, HttpContext context, IStudyStore store) =>
            WithStorageErrors(() => store.Change(state =>
            {
                var study = state.Studies.FirstOrDefault(s => s.Id == id && access(state, identity(context), s));
                if (study is null) return Results.NotFound();
                if (!Guid.TryParse(input.RequestId, out _)) return Results.BadRequest();
                var fingerprint = Fingerprint("file-delete:" + fileId, input);
                if (study.Requests.TryGetValue(input.RequestId, out var previous))
                    return previous == fingerprint ? Results.Ok(study) : Results.Conflict();
                if (study.Revision != input.ExpectedRevision || study.Stage != "Active") return Results.Conflict();
                var index = study.Files.FindIndex(f => f.Id == fileId && Visible(study, f));
                if (index < 0) return Results.NotFound();
                study.Files[index] = study.Files[index] with { Deleted = true };
                study.Revision++;
                study.Requests.Add(input.RequestId, fingerprint);
                state.Audit.Add(new(identity(context), "Removed file from demo view", study.Id, DateTimeOffset.UtcNow));
                // Retain immutable bytes for an explicit future records/retention policy.
                return Results.Ok(study);
            })));
    }
    static bool Visible(Study study, StoredFile file) => !file.Deleted &&
        (file.ParentId is null || study.Items.Any(i => i.Id == file.ParentId && !i.Deleted));
    static bool IsWithin(string path, string root) => path.Equals(root, StringComparison.OrdinalIgnoreCase) ||
        path.StartsWith(Path.TrimEndingDirectorySeparator(root) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    static string BlobPath(string root, string id)
    {
        if (!Guid.TryParseExact(id, "N", out _)) throw new InvalidDataException("Invalid generated blob identifier.");
        return Path.Combine(root, id + ".blob");
    }
    static string Fingerprint<T>(string operation, T input) => Convert.ToHexString(
        SHA256.HashData(Encoding.UTF8.GetBytes(operation + ":" + JsonSerializer.Serialize(input))));
    static IResult WithStorageErrors(Func<IResult> operation)
    {
        try { return operation(); }
        catch (IOException) { return Results.Problem("Attachment storage is unavailable; refresh before retrying.", statusCode: 503); }
        catch (UnauthorizedAccessException) { return Results.Problem("Attachment storage is unavailable; refresh before retrying.", statusCode: 503); }
    }
    static bool ValidName(string? name) => name is { Length: > 0 and <= 120 } && name == name.Trim() &&
        !name.StartsWith('.') && !name.EndsWith('.') && !name.Contains("..") &&
        !System.Text.RegularExpressions.Regex.IsMatch(name.Split('.')[0].TrimEnd(), @"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", System.Text.RegularExpressions.RegexOptions.IgnoreCase) &&
        name.All(c => char.IsAsciiLetterOrDigit(c) || c is ' ' or '-' or '_' or '.') &&
        new[] { ".txt", ".pdf", ".png", ".jpg" }.Contains(Path.GetExtension(name).ToLowerInvariant());
    static bool ValidContent(string extension, byte[] bytes)
    {
        if (extension == ".txt")
        {
            try { return StrictUtf8.GetString(bytes).All(c => !char.IsControl(c) || c is '\n' or '\r' or '\t'); }
            catch (DecoderFallbackException) { return false; }
        }
        if (extension == ".pdf") return bytes.AsSpan().StartsWith("%PDF-"u8);
        if (extension == ".png") return bytes.AsSpan().StartsWith(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 });
        if (extension == ".jpg") return bytes.Length >= 3 && bytes[0] == 255 && bytes[1] == 216 && bytes[2] == 255;
        return false;
    }
}
