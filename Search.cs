using System.Globalization;

public record SearchHit(string StudyId,string StudyTitle,object Item,string Context);
public static class SearchEndpoints
{
    static readonly string[] Kinds=["document","documentation","discussion","reply","decision","task","idea","resource","file"];
    public static void MapSearchEndpoints(this WebApplication app,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)
    {
        app.MapGet("/api/search",(HttpContext context,IStudyStore store)=>store.Read<IResult>(state=> {
            var parameters=context.Request.Query;
            if(parameters.Any(p=>!new[]{"q","page","pageSize","studyId","kind"}.Contains(p.Key)||p.Value.Count!=1))
                return Results.BadRequest(new {error="Use one value for each supported search parameter: q, page, pageSize, studyId and kind."});
            var query=parameters["q"].ToString();
            var studyId=parameters["studyId"].ToString();var kind=parameters["kind"].ToString();
            if(query.Length>200||studyId.Length>100||parameters.ContainsKey("studyId")&&string.IsNullOrWhiteSpace(studyId)||parameters.ContainsKey("kind")&&!Kinds.Contains(kind))
                return Results.BadRequest(new {error="Search text must be at most 200 characters. Use a study identifier of 1–100 characters and a supported record type when filtering."});
            var paged=parameters.ContainsKey("page")||parameters.ContainsKey("pageSize");
            var page=1;var pageSize=100;
            if(parameters.ContainsKey("page")&&(!int.TryParse(parameters["page"],NumberStyles.None,CultureInfo.InvariantCulture,out page)||page<1||page>100000)
                ||parameters.ContainsKey("pageSize")&&(!int.TryParse(parameters["pageSize"],NumberStyles.None,CultureInfo.InvariantCulture,out pageSize)||pageSize<1||pageSize>100))
                return Results.BadRequest(new {error="Page must be 1–100000 and page size 1–100."});
            var visible=state.Studies.Where(study=>access(state,identity(context),study)).ToArray();
            // Unknown and inaccessible requested studies have the same empty response, including facets.
            var scoped=visible.Where(study=>studyId.Length==0||study.Id==studyId).ToArray();
            var hits=new List<(string Study,string Kind,string Id,SearchHit Hit)>();
            var availableKinds=new HashSet<string>(StringComparer.Ordinal);
            foreach(var study in scoped) {
                foreach(var item in study.Items.Where(item=>EvidenceRules.ItemAvailable(study,item.Id)&&Kinds.Contains(item.Kind))) {
                    availableKinds.Add(item.Kind);
                    var metadata=Metadata(item);
                    if((kind.Length>0&&item.Kind!=kind)||!(item.Title+" "+item.Body+" "+metadata).Contains(query,StringComparison.OrdinalIgnoreCase))continue;
                    // Search returns bounded current text and routing metadata, never prior task bodies or raw import payloads.
                    var result=new {item.Id,item.Kind,item.Title,body=Snippet(item.Body,query),item.Version,item.Author,item.CreatedAt,item.BoardIdea};
                    hits.Add((study.Id,item.Kind,item.Id,new(study.Id,study.Title,result,Snippet(metadata,query))));
                }
                foreach(var file in study.Files.Where(file=>!file.Deleted&&(file.ParentId is null||EvidenceRules.ItemAvailable(study,file.ParentId)))) {
                    availableKinds.Add("file");
                    if((kind.Length>0&&kind!="file")||!file.Name.Contains(query,StringComparison.OrdinalIgnoreCase))continue;
                    hits.Add((study.Id,"file",file.Id,new(study.Id,study.Title,new {id=file.Id,kind="file",title=file.Name,body="File version "+file.Version+" · "+file.Status},"Filename only; file contents are not indexed.")));
                }
            }
            var total=hits.Count;var offset=(page-1)*pageSize;
            var items=hits.OrderBy(hit=>hit.Study,StringComparer.Ordinal).ThenBy(hit=>hit.Kind,StringComparer.Ordinal).ThenBy(hit=>hit.Id,StringComparer.Ordinal)
                .Skip(offset).Take(pageSize).Select(hit=>hit.Hit).ToArray();
            var hasMore=offset+items.Length<total;
            var facets=new {studies=(scoped.Length==0?[]:visible).OrderBy(s=>s.Title,StringComparer.Ordinal).Select(s=>new{s.Id,s.Title}),kinds=availableKinds.Order(StringComparer.Ordinal)};
            context.Response.Headers["X-Total-Count"]=total.ToString(CultureInfo.InvariantCulture);
            context.Response.Headers["X-Results-Truncated"]=(paged?hasMore:total>100)?"true":"false";
            return paged?Results.Ok(new {items,total,page,pageSize,hasMore,facets}):Results.Ok(items);
        }));
    }
    static string Metadata(Item item) => item.Kind switch {
        "task" when item.Task is {} task => $"Status: {task.Status} · Assignee: {Person(task.Assignee)} · Due: {task.DueDate??"Not set"}",
        "decision" when item.Decision is {} decision => $"Owner: {Person(decision.OwnerId)} · Effective: {decision.EffectiveDate} · Alternatives: {decision.Alternatives} · Reason: {decision.Reason}",
        "resource" when item.Resource is {} resource => $"Owner: {Person(resource.OwnerId)} · Source: {resource.Source} · Recorded verification: {resource.LastVerified} · {resource.Url}",
        "document" when item.Template is {} template => $"Template: {template.Title} · Version: {item.Version}",
        _ => $"Author: {item.Author} · Version: {item.Version}"
    };
    static string Person(string? id)=>id is null?"Unassigned":Demo.Identities.FirstOrDefault(user=>user.Id==id) is {} person?$"{person.Name} ({id})":id;
    static string Snippet(string text,string query) {
        const int limit=360;
        if(text.Length<=limit)return text;
        var match=query.Length==0?-1:text.IndexOf(query,StringComparison.OrdinalIgnoreCase);
        var start=Math.Max(0,match-80);var length=Math.Min(limit,text.Length-start);
        return (start>0?"…":"")+text.Substring(start,length)+(start+length<text.Length?"…":"");
    }
}
