using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

public record ProtocolDesignation(string? Kind,string? Id,string Reason,string Actor,DateTimeOffset At);
public record ProtocolInput(string? Kind,string? Id,string Reason,int ExpectedRevision,string RequestId);
public static class EvidenceRules
{
    public static bool FileAvailable(Study study,string id,AttachmentStorage storage)
    {
        if(!FileAvailable(study,id))return false;
        var file=study.Files.Single(f=>f.Id==id);
        return storage.CanReference(file);
    }
    public static bool FileAvailable(Study study,string id) => study.Files.Any(file=>file.Id==id&&!file.Deleted&&file.Status=="DemoReleased"&&(file.ParentId is null||study.Items.Any(item=>item.Id==file.ParentId&&!item.Deleted)));
}
public static class ProtocolEndpoints
{
    public static void MapProtocolEndpoints(this WebApplication app,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)
    {
        app.MapGet("/api/studies/{id}/protocol",(string id,HttpContext context,IStudyStore store,AttachmentStorage storage)=>store.Read<IResult>(state=>
        {
            var study=state.Studies.FirstOrDefault(s=>s.Id==id&&access(state,identity(context),s));
            if(study is null)return Results.NotFound();
            var selected=study.CurrentProtocol;
            var available=selected is not null&&(selected.Kind=="item"?study.Items.Any(i=>i.Id==selected.Id&&!i.Deleted&&i.Kind=="document"):selected.Kind=="file"&&EvidenceRules.FileAvailable(study,selected.Id!,storage));
            return Results.Ok(new {current=selected,history=study.ProtocolHistory,available,error=selected is not null&&!available?"The designated version is currently unavailable. Its selection and history are preserved.":null});
        }));
        app.MapPost("/api/studies/{id}/protocol",(string id,ProtocolInput input,HttpContext context,IStudyStore store,AttachmentStorage storage)=>store.Change(state=>
        {
            var actor=identity(context);
            var study=state.Studies.FirstOrDefault(s=>s.Id==id&&access(state,actor,s));
            if(study is null)return Results.NotFound();
            if(!Guid.TryParse(input.RequestId,out _)||string.IsNullOrWhiteSpace(input.Reason)||input.Reason.Length>1000||!((input.Kind is null&&input.Id is null)||(input.Kind is "item" or "file"&&!string.IsNullOrWhiteSpace(input.Id))))
                return Results.BadRequest(new {error="Select an exact text or library-file version, or clear both kind and ID. A reason of 1–1000 characters is required."});
            var fingerprint=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("protocol:"+JsonSerializer.Serialize(input))));
            if(study.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(study):Results.Conflict(new {error="Request identifier belongs to a different operation."});
            if(study.Revision!=input.ExpectedRevision)return Results.Conflict(new {error="Study changed. Refresh before changing the protocol selection."});
            if(study.Stage!="Active")return Results.Conflict(new {error="Reopen the study before changing the protocol selection."});
            if(input.Kind=="item"&&!study.Items.Any(item=>item.Id==input.Id&&!item.Deleted&&item.Kind=="document"))return Results.BadRequest(new {error="Choose a live text document version in this study."});
            if(input.Kind=="file"&&(!EvidenceRules.FileAvailable(study,input.Id!,storage)||!study.Files.Any(file=>file.Id==input.Id&&file.ParentId is null)))return Results.BadRequest(new {error="Choose a released library-file version in this study. Discussion attachments cannot be designated."});
            var selection=new ProtocolDesignation(input.Kind,input.Id,input.Reason.Trim(),actor,DateTimeOffset.UtcNow);
            study.CurrentProtocol=input.Kind is null?null:selection;
            study.ProtocolHistory.Add(selection);
            study.Revision++;study.Requests.Add(input.RequestId,fingerprint);
            state.Audit.Add(new(actor,input.Kind is null?"Cleared current protocol":"Designated current protocol",study.Id,selection.At));
            return Results.Ok(study);
        }));
    }
}
