using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

public record OrientationMark(string ContextKey,bool Completed,DateTimeOffset At);
public sealed class PersonalOrientation
{
    public int Revision {get;set;}=1;
    public Dictionary<string,OrientationMark> Marks {get;set;}=[];
    public Dictionary<string,string> Requests {get;set;}=[];
}
public record OrientationInput(string StepId,bool Completed,string ContextKey,int ExpectedRevision,string RequestId);
public record OrientationStep(string Id,string Label,string Description,string Href,string ContextKey,bool Available,bool Completed,DateTimeOffset? CompletedAt);

public static class OnboardingEndpoints
{
    public static void MapOnboardingEndpoints(this WebApplication app,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)
    {
        app.MapGet("/api/studies/{id}/onboarding",(string id,HttpContext context,IStudyStore store,AttachmentStorage storage)=>store.Read<IResult>(state=>{
            var actor=identity(context);var study=state.Studies.FirstOrDefault(s=>s.Id==id&&access(state,actor,s));
            if(study is null)return Results.NotFound();
            if(DocumentRules.StudyRole(actor)=="None")return Results.StatusCode(403);
            return Results.Ok(Project(study,actor,storage));
        }));
        app.MapPost("/api/studies/{id}/onboarding",(string id,OrientationInput input,HttpContext context,IStudyStore store,AttachmentStorage storage)=>store.Change(state=>{
            var actor=identity(context);var study=state.Studies.FirstOrDefault(s=>s.Id==id&&access(state,actor,s));
            if(study is null)return Results.NotFound();
            if(DocumentRules.StudyRole(actor)=="None")return Results.StatusCode(403);
            if(!Guid.TryParse(input.RequestId,out _)||input.StepId is not ("guidance" or "handoff" or "questions" or "actions")||input.ContextKey?.Length!=64)
                return Results.BadRequest(new {error="Choose a valid orientation step, its current context, and a request identifier."});
            var progress=study.PersonalOnboarding.GetValueOrDefault(actor)??new();
            var step=Steps(study,progress,storage).Single(s=>s.Id==input.StepId);
            if(!step.Available)return Results.Conflict(new {error="This orientation resource is unavailable. Review the current study context first."});
            // Changed evidence invalidates a prior acknowledgement, including retries of old context.
            if(input.ContextKey!=step.ContextKey)return Results.Conflict(new {error="The study context changed. Your earlier acknowledgement does not apply to the new evidence. Review it again."});
            var fingerprint=Hash(new {actor,operation="personal-orientation",input});
            if(progress.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(Project(study,actor,storage)):Results.Conflict(new {error="Request identifier already belongs to another personal update."});
            if(progress.Revision!=input.ExpectedRevision)return Results.Conflict(new {error="Your checklist changed in another tab. Refresh before saving this acknowledgement."});
            progress.Marks[input.StepId]=new(input.ContextKey,input.Completed,DateTimeOffset.UtcNow);
            progress.Requests[input.RequestId]=fingerprint;progress.Revision++;
            study.PersonalOnboarding[actor]=progress;
            // Personal reading acknowledgements never change study content/revision, roles or access.
            // They remain usable while the study is paused or closed.
            state.Audit.Add(new(actor,"Updated personal orientation acknowledgement",study.Id,DateTimeOffset.UtcNow));
            return Results.Ok(Project(study,actor,storage));
        }));
    }
    static object Project(Study study,string actor,AttachmentStorage storage)
    {
        var progress=study.PersonalOnboarding.GetValueOrDefault(actor)??new();
        var steps=Steps(study,progress,storage);
        return new {revision=progress.Revision,studyRevision=study.Revision,studyStage=study.Stage,
            contact=study.Id=="atlas"?"Riley · synthetic study lead":"Sam · synthetic study contact",steps,
            resumeStepId=steps.FirstOrDefault(step=>step.Available&&!step.Completed)?.Id};
    }
    static OrientationStep[] Steps(Study study,PersonalOrientation progress,AttachmentStorage storage)
    {
        var link="#study/"+Uri.EscapeDataString(study.Id)+"/";
        var live=study.Items.Where(item=>!item.Deleted&&EvidenceRules.ItemAvailable(study,item.Id)).ToList();
        var designated=study.CurrentProtocol;
        var document=designated?.Kind=="item"?live.FirstOrDefault(item=>item.Id==designated.Id&&item.Kind=="document"):
            designated is null?live.Where(item=>item.Kind=="document").OrderByDescending(item=>DocumentRules.Status(study,item)=="Accepted").ThenByDescending(item=>item.CreatedAt).ThenBy(item=>item.Id).FirstOrDefault():null;
        var file=designated?.Kind=="file"?study.Files.FirstOrDefault(file=>file.Id==designated.Id):null;
        var guidanceAvailable=document is not null||(file is not null&&EvidenceRules.FileAvailable(study,file.Id,storage));
        var handoff=study.Handoffs.OrderByDescending(h=>h.CreatedAt).ThenBy(h=>h.Id).FirstOrDefault();
        var handoffAvailable=handoff is not null&&handoff.Sha256==HandoffEndpoints.CaptureDigest(handoff);
        var questions=live.Where(item=>item.Kind=="discussion").OrderBy(item=>item.Id).Select(item=>new {item.Id,item.Version,content=Hash(item)}).ToArray();
        var actions=live.Where(item=>item.Kind=="task"&&item.Task?.Status!="Done").OrderBy(item=>item.Id).Select(item=>new {item.Id,item.Version,content=Hash(item),assignee=item.Task?.Assignee,status=item.Task?.Status??"Open"}).ToArray();
        OrientationStep Step(string id,string label,string description,string href,object evidence,bool available)
        {
            var key=Hash(new {id,evidence});var mark=progress.Marks.GetValueOrDefault(id);
            var completed=available&&mark?.Completed==true&&mark.ContextKey==key;
            return new(id,label,description,href,key,available,completed,completed?mark!.At:null);
        }
        return [
            Step("guidance","Review the working guidance",document is not null?document.Title+" · version "+document.Version+" · "+DocumentRules.Status(study,document):file is not null?file.Name+" · file version "+file.Version:"No available working document yet.",
                link+(designated is not null?"activity":"document"),new {designation=designated,document=document is null?null:new {document.Id,document.Version,content=Hash(document),status=DocumentRules.Status(study,document)},file=file is null?null:new {file.Id,file.Version,file.Sha256},available=guidanceAvailable},guidanceAvailable),
            Step("handoff","Read the latest handoff",handoff?.Title??"No handoff has been captured yet.",link+"handoff",new {id=handoff?.Id,sha256=handoff?.Sha256,available=handoffAvailable,projection=handoff is null?null:Hash(new {items=handoff.Content.Items.Select(i=>new {i.Id,available=EvidenceRules.ItemAvailable(study,i.Id)}),files=handoff.Content.Files.Select(f=>new {f.Id,available=CapturedFileAvailable(study,f,storage)})})},handoffAvailable),
            Step("questions","Review unresolved conversations",questions.Length==0?"No current conversations; confirm whether a question needs to be raised.":questions.Length+" current conversations to review.",link+"discussion",live.Where(item=>item.Kind is "discussion" or "reply").OrderBy(item=>item.Id).Select(item=>new {item.Id,item.Version,content=Hash(item)}).ToArray(),true),
            Step("actions","Confirm the next action",actions.Length==0?"No open tasks; confirm whether a next action is needed.":actions.Length+" open tasks with their recorded owners and status.",link+"task",actions,true)
        ];
    }
    static bool CapturedFileAvailable(Study study,StoredFile captured,AttachmentStorage storage)
    {
        var current=study.Files.FirstOrDefault(f=>f.Id==captured.Id);
        return current is not null&&current.Sha256==captured.Sha256&&current.Size==captured.Size&&current.Version==captured.Version&&current.FamilyId==captured.FamilyId&&EvidenceRules.FileAvailable(study,current.Id,storage);
    }
    static string Hash<T>(T input)=>Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(input))));
}
