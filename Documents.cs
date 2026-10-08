using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

public record DocumentVersionDetails(string FamilyId,string? PreviousVersionId);
public record DocumentReviewEvent(string From,string To,string Reason,string Actor,DateTimeOffset At);
public record DocumentReviewState(string Status,List<DocumentReviewEvent> History);
public record DocumentWriteInput(string Title,string Body,int ExpectedRevision,string RequestId,string[]? FileIds=null);
public record DocumentStateInput(string Status,string Reason,int ExpectedRevision,string RequestId);

public static class DocumentRules
{
    // Synthetic role claims are independent of application administration. Every endpoint
    // first checks current directory-group membership; these claims never grant membership.
    public static string StudyRole(string identity) => identity switch {"lead"=>"StudyLead","reviewer"=>"Reviewer","alex" or "sam"=>"Researcher",_=>"None"};
    public static string Family(Item item) => item.DocumentVersion?.FamilyId??item.Id;
    public static string Status(Study study,Item item) => study.DocumentReviews.GetValueOrDefault(item.Id)?.Status??"Draft";
    public static string? DeletionError(Study study,Item item,string identity)
    {
        if(item.Kind!="document")return null;
        if(StudyRole(identity)=="None")return "A study writing role is required.";
        if(Status(study,item) is "Accepted" or "Superseded")return "Accepted and superseded versions are retained; they cannot be removed.";
        if(study.Items.Any(other=>!other.Deleted&&other.Id!=item.Id&&(other.DocumentId==item.Id||other.ParentId==item.Id||other.DocumentVersion?.PreviousVersionId==item.Id||(other.Task?.Links.Contains(item.Id)??false)||(other.Provenance?.ReferenceTargetIds.Contains(item.Id)??false)))||study.Files.Any(file=>!file.Deleted&&(file.FamilyId==item.Id||(file.Provenance?.ReferenceTargetIds.Contains(item.Id)??false))))
            return "This exact version is referenced by live study content. Preserve its evidence before removal.";
        return null;
    }
    public static bool CanRequestState(string role,string status) => status switch
    {
        "Review"=>role is "Researcher" or "Reviewer" or "StudyLead",
        "Draft"=>role is "Reviewer" or "StudyLead",
        "Accepted" or "Superseded"=>role=="StudyLead",
        _=>false
    };
}

public static class DocumentEndpoints
{
    public static void MapDocumentEndpoints(this WebApplication app,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)
    {
        app.MapGet("/api/studies/{id}/documents",(string id,HttpContext context,IStudyStore store)=>store.Read<IResult>(state=>
        {
            var study=state.Studies.FirstOrDefault(s=>s.Id==id&&access(state,identity(context),s));
            return study is null?Results.NotFound():Results.Ok(new {studyRole=DocumentRules.StudyRole(identity(context)),revision=study.Revision,versions=study.Items.Where(item=>!item.Deleted&&item.Kind=="document").Select(item=>new {item,familyId=DocumentRules.Family(item),previousVersionId=item.DocumentVersion?.PreviousVersionId,status=DocumentRules.Status(study,item),history=study.DocumentReviews.GetValueOrDefault(item.Id)?.History??[]})});
        }));
        app.MapPost("/api/studies/{id}/documents",(string id,DocumentWriteInput input,HttpContext context,IStudyStore store,AttachmentStorage storage)=>Write(id,null,input,context,store,storage,identity,access));
        app.MapPost("/api/studies/{id}/documents/{versionId}/versions",(string id,string versionId,DocumentWriteInput input,HttpContext context,IStudyStore store,AttachmentStorage storage)=>Write(id,versionId,input,context,store,storage,identity,access));
        app.MapPost("/api/studies/{id}/documents/{versionId}/state",(string id,string versionId,DocumentStateInput input,HttpContext context,IStudyStore store,AttachmentStorage storage)=>store.Change(state=>
        {
            var actor=identity(context);
            var study=state.Studies.FirstOrDefault(s=>s.Id==id&&access(state,actor,s));
            if(study is null)return Results.NotFound();
            if(!new[]{"Draft","Review","Accepted","Superseded"}.Contains(input.Status)||string.IsNullOrWhiteSpace(input.Reason)||input.Reason.Length>1000||!Guid.TryParse(input.RequestId,out _))return Results.BadRequest(new {error="Provide a valid state, a reason of 1–1000 characters, and a request identifier."});
            if(!DocumentRules.CanRequestState(DocumentRules.StudyRole(actor),input.Status))return Results.StatusCode(403);
            var fingerprint=Fingerprint("document-state:"+versionId,input);
            if(study.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(study):Results.Conflict(new {error="Request identifier already belongs to another operation."});
            if(study.Revision!=input.ExpectedRevision)return Results.Conflict(new {error="Study changed. Refresh before changing document state."});
            if(study.Stage!="Active")return Results.Conflict(new {error="Reopen the study before changing document state."});
            var item=study.Items.FirstOrDefault(i=>i.Id==versionId&&!i.Deleted&&i.Kind=="document");
            if(item is null)return Results.NotFound();
            var before=DocumentRules.Status(study,item);
            if(!((before=="Draft"&&input.Status=="Review")||(before=="Review"&&input.Status is "Draft" or "Accepted")||(before=="Accepted"&&input.Status=="Superseded")))return Results.Conflict(new {error="Unsupported state transition. Use Draft → Review → Accepted → Superseded; reviewers may return Review to Draft."});
            if(input.Status=="Superseded"&&study.CurrentProtocol is {Kind:"item"} designation&&designation.Id==versionId)return Results.Conflict(new {error="Change or clear the current protocol designation before superseding this exact version."});
            if(input.Status=="Accepted"&&study.Items.Any(other=>other.Id!=item.Id&&!other.Deleted&&other.Kind=="document"&&DocumentRules.Family(other)==DocumentRules.Family(item)&&DocumentRules.Status(study,other)=="Accepted"))return Results.Conflict(new {error="Explicitly supersede the previously accepted version in this family before accepting another."});
            if(input.Status=="Accepted"&&item.FileIds.Any(file=>!EvidenceRules.FileAvailable(study,file,storage)))return Results.Conflict(new {error="An exact file citation is unavailable or no longer released. Resolve the evidence before acceptance."});
            var events=study.DocumentReviews.GetValueOrDefault(item.Id)?.History.ToList()??[];
            events.Add(new(before,input.Status,input.Reason.Trim(),actor,DateTimeOffset.UtcNow));
            study.DocumentReviews[item.Id]=new(input.Status,events);
            study.Revision++;study.Requests.Add(input.RequestId,fingerprint);
            state.Audit.Add(new(actor,"Document state: "+before+" → "+input.Status,item.Id,DateTimeOffset.UtcNow));
            return Results.Ok(study);
        }));
    }
    static IResult Write(string id,string? previousId,DocumentWriteInput input,HttpContext context,IStudyStore store,AttachmentStorage storage,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)=>store.Change(state=>
    {
        var actor=identity(context);
        var study=state.Studies.FirstOrDefault(s=>s.Id==id&&access(state,actor,s));
        if(study is null)return Results.NotFound();
        if(DocumentRules.StudyRole(actor)=="None")return Results.StatusCode(403);
        if(string.IsNullOrWhiteSpace(input.Title)||input.Title.Length>180||string.IsNullOrWhiteSpace(input.Body)||input.Body.Length>20000||!Guid.TryParse(input.RequestId,out _))return Results.BadRequest(new {error="Provide title (1–180), content (1–20000), and request identifier."});
        var fingerprint=Fingerprint("document-version:"+(previousId??"new"),input);
        if(study.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(study):Results.Conflict(new {error="Request identifier already belongs to another operation."});
        if(study.Revision!=input.ExpectedRevision)return Results.Conflict(new {error="Study changed. Your draft is retained; refresh before retrying."});
        if(study.Stage!="Active")return Results.Conflict(new {error="Reopen the study before adding a document version."});
        var previous=previousId is null?null:study.Items.FirstOrDefault(i=>i.Id==previousId&&!i.Deleted&&i.Kind=="document");
        if(previousId is not null&&previous is null)return Results.NotFound();
        var files=input.FileIds??[];
        if(files.Length>30||files.Distinct().Count()!=files.Length||files.Any(file=>!EvidenceRules.FileAvailable(study,file,storage)))return Results.BadRequest(new {error="File evidence must reference distinct released exact versions in this study."});
        var itemId=Guid.NewGuid().ToString();
        var family=previous is null?itemId:DocumentRules.Family(previous);
        var version=previous is null?1:study.Items.Where(i=>i.Kind=="document"&&DocumentRules.Family(i)==family).Max(i=>i.Version)+1;
        var item=new Item(itemId,"document",input.Title.Trim(),input.Body,null,null,version,actor,DateTimeOffset.UtcNow){DocumentVersion=new(family,previousId),FileIds=files};
        study.Items.Add(item);study.DocumentReviews[itemId]=new("Draft",[]);
        study.Requests.Add(input.RequestId,fingerprint);study.Revision++;
        state.Audit.Add(new(actor,previous is null?"Created document family":"Added immutable document version",item.Id,DateTimeOffset.UtcNow));
        return Results.Ok(study);
    });
    static string Fingerprint<T>(string operation,T input)=>Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(operation+":"+JsonSerializer.Serialize(input))));
}
