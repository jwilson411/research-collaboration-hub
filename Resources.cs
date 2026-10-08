using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

public record DocumentTemplate(string Id,string Title);
public record StudyTemplate(string Id,string Title,string Description,string Body);
public record ResourcePointer(string? Url,string OwnerId,string Source,string LastVerified);
public record ResourceInput(string Title,string? Body,string? Url,string OwnerId,string Source,string LastVerified,int ExpectedRevision,string RequestId);

public static class ResourceEndpoints
{
    public static readonly StudyTemplate[] Templates = [
        new("protocol","Study protocol","A starting outline for methods and review; creating it does not approve a protocol.","Purpose and research question\n[Describe the question and intended outcome.]\n\nScope and exclusions\n[State what is included and excluded.]\n\nMethods and assumptions\n[Describe the proposed approach, measures, and limitations.]\n\nData and access\n[Record approved sources and required access. Do not enter patient data in this demo.]\n\nReview and next actions\n[Name the reviewer, unresolved questions, and next review date.]"),
        new("handoff","Study handoff notes","Prepare a narrative before capturing exact evidence in an immutable handoff.","Current position\n[Describe stage and the latest agreed direction.]\n\nCurrent protocol and evidence\n[Identify exact document and file versions.]\n\nDecisions and rationale\n[Link retained decision records and unresolved alternatives.]\n\nOpen questions and next actions\n[Name each action owner and due date.]\n\nResume checklist\n[Describe the first steps for a returning collaborator.]"),
        new("orientation","Collaborator orientation","Help a new or returning collaborator find people, context, and next steps.","Start here\n[Explain the study purpose and current stage.]\n\nPeople and responsibilities\n[Identify the study contact and review responsibilities. Access remains directory-group controlled.]\n\nRead first\n[Point to the current protocol, latest handoff, and current decisions.]\n\nDiscuss and contribute\n[Identify the active question, brainstorming session, and next action.]\n\nLocal resources\n[Record resource owners and when pointers were last verified.]")
    ];
    public static void MapResourceEndpoints(this WebApplication app,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)
    {
        app.MapGet("/api/studies/{id}/templates",(string id,HttpContext c,IStudyStore store)=>store.Read<IResult>(s=>s.Studies.Any(st=>st.Id==id&&access(s,identity(c),st))?Results.Ok(Templates):Results.NotFound()));
        app.MapGet("/api/studies/{id}/resources",(string id,HttpContext c,IStudyStore store)=>store.Read<IResult>(s=> {
            var st=s.Studies.FirstOrDefault(st=>st.Id==id&&access(s,identity(c),st));
            return st is null?Results.NotFound():Results.Ok(new {revision=st.Revision,resources=st.Items.Where(i=>i.Kind=="resource"&&EvidenceRules.ItemAvailable(st,i.Id))});
        }));
        app.MapPost("/api/studies/{id}/resources",(string id,ResourceInput input,HttpContext c,IStudyStore store)=>store.Change(s=> {
            var actor=identity(c);var st=s.Studies.FirstOrDefault(st=>st.Id==id&&access(s,actor,st));
            if(st is null)return Results.NotFound();
            if(DocumentRules.StudyRole(actor)=="None")return Results.StatusCode(403);
            var url=string.IsNullOrWhiteSpace(input.Url)?null:input.Url.Trim();
            if(string.IsNullOrWhiteSpace(input.Title)||input.Title.Length>180||input.Body?.Length>20000||string.IsNullOrWhiteSpace(input.Source)||input.Source.Length>300||!Guid.TryParse(input.RequestId,out _)||
               (url is null&&string.IsNullOrWhiteSpace(input.Body))||url?.Length>2000||
               (url is not null&&(!Uri.TryCreate(url,UriKind.Absolute,out var uri)||uri.Scheme is not ("https" or "http")||string.IsNullOrEmpty(uri.Host)||!string.IsNullOrEmpty(uri.UserInfo)))||
               !DateOnly.TryParseExact(input.LastVerified,"yyyy-MM-dd",CultureInfo.InvariantCulture,DateTimeStyles.None,out var date)||date.Year<1900||date>DateOnly.FromDateTime(DateTime.UtcNow)||
               !Demo.Identities.Any(user=>user.Id==input.OwnerId&&Demo.Groups.GetValueOrDefault(user.Id,[]).Contains(st.GroupId)))
                return Results.BadRequest(new {error="Provide a title, local description or HTTP(S) URL without credentials, current study member owner, source, and a past or current verification date (YYYY-MM-DD). Pointers are not fetched or verified by this app."});
            var fingerprint=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("resource:"+JsonSerializer.Serialize(input))));
            if(st.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(st):Results.Conflict(new {error="Request identifier belongs to another operation."});
            if(st.Stage!="Active"||st.Revision!=input.ExpectedRevision)return Results.Conflict(new {error="Refresh the active study before saving this pointer. Your draft was not saved."});
            var item=new Item(Guid.NewGuid().ToString(),"resource",input.Title.Trim(),input.Body?.Trim()??"",null,null,1,actor,DateTimeOffset.UtcNow){Resource=new(url,input.OwnerId,input.Source.Trim(),input.LastVerified)};
            st.Items.Add(item);st.Revision++;st.Requests.Add(input.RequestId,fingerprint);s.Audit.Add(new(actor,"Added resource pointer",item.Id,DateTimeOffset.UtcNow));return Results.Ok(st);
        }));
    }
}
