using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

public record DocumentTemplate(string Id,string Title,
    [property:JsonIgnore(Condition=JsonIgnoreCondition.WhenWritingNull)] string? VersionId=null,
    [property:JsonIgnore(Condition=JsonIgnoreCondition.WhenWritingNull)] int? Version=null,
    [property:JsonIgnore(Condition=JsonIgnoreCondition.WhenWritingNull)] string? Sha256=null);
public record StudyTemplate(string Id,string Title,string Description,string Body);
public record TemplateDefinition(string Id,string VersionId,int Version,string? PreviousVersionId,string Title,string Description,string Body,string Reason,string Actor,DateTimeOffset CreatedAt);
public record TemplateDefinitionInput(string Title,string Description,string Body,string Reason,int ExpectedRevision,string RequestId);
public record ResourceVersionDetails(string FamilyId,string PreviousVersionId,string Operation,string Reason);
public record ResourcePointer(string? Url,string OwnerId,string Source,string LastVerified,
    [property:JsonIgnore(Condition=JsonIgnoreCondition.WhenWritingNull)] ResourceVersionDetails? VersionDetails=null);
public record ResourceInput(string Title,string? Body,string? Url,string OwnerId,string Source,string LastVerified,int ExpectedRevision,string RequestId,
    [property:JsonIgnore(Condition=JsonIgnoreCondition.WhenWritingNull)] string? Reason=null);
public record ResourceVerifyInput(string LastVerified,string Reason,int ExpectedRevision,string RequestId);

public static class ResourceRules
{
    public static string Family(Item item)=>item.Resource?.VersionDetails?.FamilyId??item.Id;
    public static bool HasSuccessor(Study study,string id)=>study.Items.Any(item=>item.Resource?.VersionDetails?.PreviousVersionId==id);
    public static string? DeletionError(Study study,Item item)=>item.Kind=="resource"&&(item.Resource?.VersionDetails is not null||HasSuccessor(study,item.Id))
        ?"Resource versions are retained as an immutable history; add a replacement or reverification instead.":null;
}
public static class ResourceEndpoints
{
    public static readonly StudyTemplate[] Templates = [
        new("protocol","Study protocol","A starting outline for methods and review; creating it does not approve a protocol.","Purpose and research question\n[Describe the question and intended outcome.]\n\nScope and exclusions\n[State what is included and excluded.]\n\nMethods and assumptions\n[Describe the proposed approach, measures, and limitations.]\n\nData and access\n[Record approved sources and required access. Do not enter patient data in this demo.]\n\nReview and next actions\n[Name the reviewer, unresolved questions, and next review date.]"),
        new("handoff","Study handoff notes","Prepare a narrative before capturing exact evidence in an immutable handoff.","Current position\n[Describe stage and the latest agreed direction.]\n\nCurrent protocol and evidence\n[Identify exact document and file versions.]\n\nDecisions and rationale\n[Link retained decision records and unresolved alternatives.]\n\nOpen questions and next actions\n[Name each action owner and due date.]\n\nResume checklist\n[Describe the first steps for a returning collaborator.]"),
        new("orientation","Collaborator orientation","Help a new or returning collaborator find people, context, and next steps.","Start here\n[Explain the study purpose and current stage.]\n\nPeople and responsibilities\n[Identify the study contact and review responsibilities. Access remains directory-group controlled.]\n\nRead first\n[Point to the current protocol, latest handoff, and current decisions.]\n\nDiscuss and contribute\n[Identify the active question, brainstorming session, and next action.]\n\nLocal resources\n[Record resource owners and when pointers were last verified.]")
    ];
    public static List<TemplateDefinition> Definitions(Study study)=>study.TemplateDefinitions.Count>0?study.TemplateDefinitions:Templates.Select(template=>new TemplateDefinition(template.Id,$"default:{study.Id}:{template.Id}:1",1,null,template.Title,template.Description,template.Body,"Shipped synthetic starting outline","synthetic-catalog",DateTimeOffset.Parse("2026-09-01T00:00:00Z",CultureInfo.InvariantCulture))).ToList();
    public static string DefinitionHash(TemplateDefinition definition)=>Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(definition))));
    static object TemplateCatalog(Study study)=>new {revision=study.Revision,templates=Definitions(study).GroupBy(definition=>definition.Id).Select(group=>group.MaxBy(definition=>definition.Version)),versions=Definitions(study)};
    static object ResourceDetail(Study study,Item item)=>new {item,current=!ResourceRules.HasSuccessor(study,item.Id),history=study.Items.Where(other=>other.Kind=="resource"&&ResourceRules.Family(other)==ResourceRules.Family(item)&&EvidenceRules.ItemAvailable(study,other.Id)).OrderBy(other=>other.Version)};
    public static void MapResourceEndpoints(this WebApplication app,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)
    {
        app.MapGet("/api/studies/{id}/templates",(string id,HttpContext context,IStudyStore store)=>store.Read<IResult>(state=> {
            var study=state.Studies.FirstOrDefault(study=>study.Id==id&&access(state,identity(context),study));
            return study is null?Results.NotFound():Results.Ok(Definitions(study).GroupBy(definition=>definition.Id).Select(group=>group.MaxBy(definition=>definition.Version)));
        }));
        app.MapGet("/api/studies/{id}/templates/{templateId}/versions",(string id,string templateId,HttpContext context,IStudyStore store)=>store.Read<IResult>(state=> {
            var study=state.Studies.FirstOrDefault(study=>study.Id==id&&access(state,identity(context),study));
            if(study is null)return Results.NotFound();
            var definitions=Definitions(study).Where(definition=>definition.Id==templateId).OrderBy(definition=>definition.Version).ToArray();
            return definitions.Length==0?Results.NotFound():Results.Ok(definitions);
        }));
        app.MapPost("/api/studies/{id}/templates",(string id,TemplateDefinitionInput input,HttpContext context,IStudyStore store)=>WriteTemplate(id,null,input,context,store,identity,access));
        app.MapPost("/api/studies/{id}/templates/{templateId}/versions",(string id,string templateId,TemplateDefinitionInput input,HttpContext context,IStudyStore store)=>WriteTemplate(id,templateId,input,context,store,identity,access));
        app.MapGet("/api/studies/{id}/resources",(string id,HttpContext context,IStudyStore store)=>store.Read<IResult>(state=> {
            var study=state.Studies.FirstOrDefault(study=>study.Id==id&&access(state,identity(context),study));
            if(study is null)return Results.NotFound();
            var resources=study.Items.Where(item=>item.Kind=="resource"&&EvidenceRules.ItemAvailable(study,item.Id)).ToArray();
            return Results.Ok(new {revision=study.Revision,resources,current=resources.Where(item=>!ResourceRules.HasSuccessor(study,item.Id)),history=resources.Where(item=>ResourceRules.HasSuccessor(study,item.Id))});
        }));
        app.MapGet("/api/studies/{id}/resources/{resourceId}",(string id,string resourceId,HttpContext context,IStudyStore store)=>store.Read<IResult>(state=> {
            var study=state.Studies.FirstOrDefault(study=>study.Id==id&&access(state,identity(context),study));
            var item=study?.Items.FirstOrDefault(item=>item.Id==resourceId&&item.Kind=="resource"&&EvidenceRules.ItemAvailable(study,item.Id));
            return item is null?Results.NotFound():Results.Ok(ResourceDetail(study!,item));
        }));
        app.MapPost("/api/studies/{id}/resources",(string id,ResourceInput input,HttpContext context,IStudyStore store)=>WriteResource(id,null,input,null,context,store,identity,access));
        app.MapPost("/api/studies/{id}/resources/{resourceId}/replace",(string id,string resourceId,ResourceInput input,HttpContext context,IStudyStore store)=>WriteResource(id,resourceId,input,null,context,store,identity,access));
        app.MapPost("/api/studies/{id}/resources/{resourceId}/reverify",(string id,string resourceId,ResourceVerifyInput input,HttpContext context,IStudyStore store)=>WriteResource(id,resourceId,null,input,context,store,identity,access));
    }
    static IResult WriteTemplate(string id,string? templateId,TemplateDefinitionInput input,HttpContext context,IStudyStore store,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)=>store.Change(state=> {
        var actor=identity(context);var study=state.Studies.FirstOrDefault(study=>study.Id==id&&access(state,actor,study));
        if(study is null)return Results.NotFound();
        if(DocumentRules.StudyRole(actor)!="StudyLead")return Results.StatusCode(403);
        if(string.IsNullOrWhiteSpace(input.Title)||input.Title.Length>180||string.IsNullOrWhiteSpace(input.Description)||input.Description.Length>1000||string.IsNullOrWhiteSpace(input.Body)||input.Body.Length>20000||string.IsNullOrWhiteSpace(input.Reason)||input.Reason.Length>1000||!Guid.TryParse(input.RequestId,out _))return Results.BadRequest(new {error="Provide title (1–180), description (1–1000), body (1–20000), reason (1–1000), and request identifier."});
        var fingerprint=Fingerprint("template:"+(templateId??"new"),input);
        if(study.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(TemplateCatalog(study)):Results.Conflict();
        if(study.Stage!="Active"||study.Revision!=input.ExpectedRevision)return Results.Conflict(new {error="Refresh the active study before saving a new template definition."});
        var definitions=Definitions(study);
        var previous=templateId is null?null:definitions.Where(definition=>definition.Id==templateId).MaxBy(definition=>definition.Version);
        if(templateId is not null&&previous is null)return Results.NotFound();
        var next=new TemplateDefinition(templateId??Guid.NewGuid().ToString("N"),Guid.NewGuid().ToString("N"),(previous?.Version??0)+1,previous?.VersionId,input.Title.Trim(),input.Description.Trim(),input.Body,input.Reason.Trim(),actor,DateTimeOffset.UtcNow);
        study.TemplateDefinitions=definitions.ToList();study.TemplateDefinitions.Add(next);
        study.Revision++;study.Requests.Add(input.RequestId,fingerprint);state.Audit.Add(new(actor,"Added template definition version",next.VersionId,DateTimeOffset.UtcNow));
        return Results.Ok(TemplateCatalog(study));
    });
    static IResult WriteResource(string id,string? previousId,ResourceInput? supplied,ResourceVerifyInput? verification,HttpContext context,IStudyStore store,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)=>store.Change(state=> {
        var actor=identity(context);var study=state.Studies.FirstOrDefault(study=>study.Id==id&&access(state,actor,study));
        if(study is null)return Results.NotFound();
        if(DocumentRules.StudyRole(actor)=="None")return Results.StatusCode(403);
        var previous=previousId is null?null:study.Items.FirstOrDefault(item=>item.Id==previousId&&item.Kind=="resource"&&item.Resource is not null&&EvidenceRules.ItemAvailable(study,item.Id));
        if(previousId is not null&&previous is null)return Results.NotFound();
        var operation=verification is not null?"Reverified":previousId is null?"Created":"Replaced";
        var input=supplied??new ResourceInput(previous!.Title,previous.Body,previous.Resource!.Url,previous.Resource.OwnerId,previous.Resource.Source,verification!.LastVerified,verification.ExpectedRevision,verification.RequestId,verification.Reason);
        var url=string.IsNullOrWhiteSpace(input.Url)?null:input.Url.Trim();
        if(string.IsNullOrWhiteSpace(input.Title)||input.Title.Length>180||input.Body?.Length>20000||string.IsNullOrWhiteSpace(input.Source)||input.Source.Length>300||!Guid.TryParse(input.RequestId,out _)||
            (url is null&&string.IsNullOrWhiteSpace(input.Body))||url?.Length>2000||
            (url is not null&&(!Uri.TryCreate(url,UriKind.Absolute,out var uri)||uri.Scheme is not ("https" or "http")||string.IsNullOrEmpty(uri.Host)||!string.IsNullOrEmpty(uri.UserInfo)))||
            !DateOnly.TryParseExact(input.LastVerified,"yyyy-MM-dd",CultureInfo.InvariantCulture,DateTimeStyles.None,out var date)||date.Year<1900||date>DateOnly.FromDateTime(DateTime.UtcNow)||
            !Demo.Identities.Any(user=>user.Id==input.OwnerId&&Demo.Groups.GetValueOrDefault(user.Id,[]).Contains(study.GroupId))||
            (previousId is not null&&(string.IsNullOrWhiteSpace(input.Reason)||input.Reason.Length>1000))||input.Reason?.Length>1000)
            return Results.BadRequest(new {error="Provide a title, local description or HTTP(S) URL without credentials, current study member owner, source, past or current verification date, and a reason for changes. Pointers are not fetched or verified by this app."});
        // Preserve the legacy create fingerprint; newly optional null fields are omitted.
        var fingerprint=previousId is null?Fingerprint("resource",input):Fingerprint("resource:"+operation+":"+previousId,verification is not null?(object)verification:input);
        if(study.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(study):Results.Conflict(new {error="Request identifier belongs to another operation."});
        if(study.Stage!="Active"||study.Revision!=input.ExpectedRevision)return Results.Conflict(new {error="Refresh the active study before saving this pointer. Your draft was not saved."});
        if(previous is not null&&ResourceRules.HasSuccessor(study,previous.Id))return Results.Conflict(new {error="This exact resource already has a successor. Open the current version before changing it."});
        var item=new Item(Guid.NewGuid().ToString(),"resource",input.Title.Trim(),input.Body?.Trim()??"",previous?.ParentId,null,(previous?.Version??0)+1,actor,DateTimeOffset.UtcNow){Resource=new(url,input.OwnerId,input.Source.Trim(),input.LastVerified,previous is null?null:new(ResourceRules.Family(previous),previous.Id,operation,input.Reason!.Trim()))};
        study.Items.Add(item);study.Revision++;study.Requests.Add(input.RequestId,fingerprint);state.Audit.Add(new(actor,operation+" resource pointer",item.Id,DateTimeOffset.UtcNow));return Results.Ok(study);
    });
    static string Fingerprint<T>(string operation,T input)=>Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(operation+":"+JsonSerializer.Serialize(input))));
}
