using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

public record TaskRevision(int Version, string Title, string Body, string? Assignee, string? DueDate, string Status, string[] Links, string Actor, DateTimeOffset At);
public record TaskDetails(string? Assignee, string? DueDate, string Status, string[] Links, List<TaskRevision> History);
public record TaskInput(string Title, string Body, string? Assignee, string? DueDate, string Status, string[]? Links, int ExpectedRevision, string RequestId);

public static class TaskEndpoints
{
    public static void MapTaskEndpoints(this WebApplication app, Func<HttpContext,string> identity, Func<State,string,Study,bool> access)
    {
        app.MapGet("/api/studies/{id}/assignees", (string id,HttpContext context,IStudyStore store) => store.Read<IResult>(state =>
        {
            var study=state.Studies.FirstOrDefault(s=>s.Id==id&&access(state,identity(context),s));
            return study is null ? Results.NotFound() : Results.Ok(Demo.Identities.Where(user=>Demo.Groups.GetValueOrDefault(user.Id,[]).Contains(study.GroupId)).Select(user=>new {user.Id,user.Name}));
        }));
        app.MapPost("/api/studies/{id}/tasks", (string id,TaskInput input,HttpContext context,IStudyStore store) => Change(id,null,input,context,store,identity,access));
        app.MapPost("/api/studies/{id}/tasks/{taskId}", (string id,string taskId,TaskInput input,HttpContext context,IStudyStore store) => Change(id,taskId,input,context,store,identity,access));
    }

    static IResult Change(string id,string? taskId,TaskInput input,HttpContext context,IStudyStore store,Func<HttpContext,string> identity,Func<State,string,Study,bool> access) => store.Change(state =>
    {
        var actor=identity(context);
        var study=state.Studies.FirstOrDefault(s=>s.Id==id&&access(state,actor,s));
        if(study is null)return Results.NotFound();
        if(!Guid.TryParse(input.RequestId,out _) || string.IsNullOrWhiteSpace(input.Title) || input.Title.Length>180 || string.IsNullOrWhiteSpace(input.Body) || input.Body.Length>20000 || !new[]{"Open","In progress","Blocked","Done"}.Contains(input.Status))
            return Results.BadRequest(new {error="Provide title (1–180), description (1–20000), valid status, and request identifier."});
        var fingerprint=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("task:"+(taskId??"new")+":"+JsonSerializer.Serialize(input))));
        if(study.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(study):Results.Conflict(new {error="Request identifier already belongs to a different operation."});
        if(study.Revision!=input.ExpectedRevision)return Results.Conflict(new {error="Study changed. Your draft was not saved; refresh before retrying."});
        if(study.Stage!="Active")return Results.Conflict(new {error="Reopen the study before changing a task."});
        var current=taskId is null?null:study.Items.FirstOrDefault(i=>i.Id==taskId&&i.Kind=="task"&&!i.Deleted);
        if(taskId is not null&&current is null)return Results.NotFound();
        var assignee=string.IsNullOrWhiteSpace(input.Assignee)?null:input.Assignee;
        if(assignee is not null&&(!Demo.Identities.Any(i=>i.Id==assignee)||!Demo.Groups.GetValueOrDefault(assignee,[]).Contains(study.GroupId)))
            return Results.BadRequest(new {error="Assignee must currently belong to the study's authoritative group. Assignment never grants access."});
        var dueDate=string.IsNullOrWhiteSpace(input.DueDate)?null:input.DueDate;
        if(dueDate is not null&&(!DateOnly.TryParseExact(dueDate,"yyyy-MM-dd",CultureInfo.InvariantCulture,DateTimeStyles.None,out var parsed)||parsed.Year<1900||parsed.Year>2100))
            return Results.BadRequest(new {error="Due date must be YYYY-MM-DD between 1900-01-01 and 2100-12-31."});
        var links=input.Links??[];
        if(links.Length>30||links.Distinct().Count()!=links.Length||links.Any(link=>string.IsNullOrWhiteSpace(link)||!study.Items.Any(i=>i.Id==link&&!i.Deleted&&new[]{"document","documentation","discussion","reply","decision","idea"}.Contains(i.Kind))))
            return Results.BadRequest(new {error="Evidence must contain up to 30 distinct live records from this study."});
        var now=DateTimeOffset.UtcNow;
        var history=current?.Task?.History.ToList()??[];
        if(current is not null)
            history.Add(new(current.Version,current.Title,current.Body,current.Task?.Assignee,current.Task?.DueDate,current.Task?.Status??"Open",current.Task?.Links??(current.DocumentId is {} document?[document]:[]),current.Author,current.CreatedAt));
        var details=new TaskDetails(assignee,dueDate,input.Status,links,history);
        var item=new Item(taskId??Guid.NewGuid().ToString(),"task",input.Title.Trim(),input.Body,null,null,(current?.Version??0)+1,actor,now){Task=details};
        if(current is null)study.Items.Add(item);else study.Items[study.Items.IndexOf(current)]=item;
        study.Requests.Add(input.RequestId,fingerprint);study.Revision++;
        state.Audit.Add(new(actor,current is null?"Created task":"Updated task",study.Id,now));
        return Results.Ok(study);
    });
}
