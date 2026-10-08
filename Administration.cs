using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

public record ConfigurationChange(int Revision, string Actor, string Action, string Target, string Before, string After, DateTimeOffset At);
public record MappingInput(string StudyId, string GroupId, int ExpectedRevision, string RequestId);
public record RoleInput(string Identity, string Role, int ExpectedRevision, string RequestId);
public static class AdministrationEndpoints
{
    public static void MapAdminEndpoints(this WebApplication app, Func<HttpContext,string> identity,
        Func<State,string,Study,bool> access, Func<State,string,bool> admin)
    {
        app.MapGet("/api/admin", (HttpContext context,IStudyStore store) => store.Read<IResult>(state =>
            admin(state,identity(context)) ? Results.Ok(new {
                configRevision=state.ConfigRevision, roles=state.Roles,
                mappings=state.Studies.Select(study=>new {studyId=study.Id,groupId=study.GroupId}),
                audit=state.Audit, configurationHistory=state.ConfigurationHistory,
                identities=Demo.Identities, groups=Demo.Groups,
                effectiveAccess=Demo.Identities.Select(user=>new {identity=user.Id,studies=state.Studies.Where(study=>access(state,user.Id,study)).Select(study=>study.Id)})
            }) : Results.StatusCode(403)));
        app.MapPost("/api/admin/mapping", (MappingInput input,HttpContext context,IStudyStore store) => store.Change(state => {
            var actor=identity(context);
            if(!admin(state,actor))return Results.StatusCode(403);
            if(!Guid.TryParse(input.RequestId,out _) || input.ExpectedRevision<1 || string.IsNullOrWhiteSpace(input.StudyId) || !new[]{"demo-group-a","demo-group-b"}.Contains(input.GroupId))return Results.BadRequest(new {error="Provide a study, existing synthetic group, configuration revision and request identifier."});
            var fingerprint=Fingerprint("mapping",input);
            var replay=Replay(state,input.RequestId,fingerprint);if(replay is not null)return replay;
            if(state.ConfigRevision!=input.ExpectedRevision)return Conflict();
            var study=state.Studies.FirstOrDefault(study=>study.Id==input.StudyId);if(study is null)return Results.BadRequest(new {error="Unknown study."});
            var before=study.GroupId;study.GroupId=input.GroupId;study.Revision++;
            Record(state,actor,"Changed group mapping",study.Id,before,input.GroupId,input.RequestId,fingerprint);
            return Results.Ok(new {configRevision=state.ConfigRevision});
        }));
        app.MapPost("/api/admin/role", (RoleInput input,HttpContext context,IStudyStore store) => store.Change(state => {
            var actor=identity(context);
            if(!admin(state,actor))return Results.StatusCode(403);
            if(!Guid.TryParse(input.RequestId,out _) || input.ExpectedRevision<1 || !Demo.Identities.Any(user=>user.Id==input.Identity) || !new[]{"Researcher","Administrator"}.Contains(input.Role))return Results.BadRequest(new {error="Provide a known synthetic identity, valid role, configuration revision and request identifier."});
            var fingerprint=Fingerprint("role",input);
            var replay=Replay(state,input.RequestId,fingerprint);if(replay is not null)return replay;
            if(state.ConfigRevision!=input.ExpectedRevision)return Conflict();
            if(input.Identity==actor && input.Role!="Administrator")return Results.BadRequest(new {error="Cannot remove your own administrator role."});
            var before=state.Roles.GetValueOrDefault(input.Identity,"Researcher");state.Roles[input.Identity]=input.Role;
            Record(state,actor,"Changed application role",input.Identity,before,input.Role,input.RequestId,fingerprint);
            return Results.Ok(new {configRevision=state.ConfigRevision});
        }));
    }
    static string Fingerprint<T>(string operation,T value)=>Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(operation+":"+JsonSerializer.Serialize(value))));
    static IResult? Replay(State state,string requestId,string fingerprint) => state.ConfigRequests.TryGetValue(requestId,out var prior)
        ? prior==fingerprint ? Results.Ok(new {configRevision=state.ConfigRevision}) : Results.Conflict(new {error="This request identifier already belongs to another configuration change."}) : null;
    static IResult Conflict()=>Results.Conflict(new {error="Configuration changed. Your selection was not saved. Refresh the admin page and review the latest values before retrying."});
    static void Record(State state,string actor,string action,string target,string before,string after,string requestId,string fingerprint)
    {
        state.ConfigRevision++;
        var now=DateTimeOffset.UtcNow;
        state.ConfigRequests.Add(requestId,fingerprint);
        state.ConfigurationHistory.Add(new(state.ConfigRevision,actor,action,target,before,after,now));
        state.Audit.Add(new(actor,action,target,now));
    }
}
