using System.Globalization;

public record SearchHit(string StudyId,string StudyTitle,object Item);
public static class SearchEndpoints
{
    public static void MapSearchEndpoints(this WebApplication app,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)
    {
        app.MapGet("/api/search",(HttpContext context,IStudyStore store)=>store.Read<IResult>(state=> {
            var parameters=context.Request.Query;
            if(parameters["q"].Count>1 || parameters["page"].Count>1 || parameters["pageSize"].Count>1)
                return Results.BadRequest(new {error="Use one query, page, and page size value."});
            var query=parameters["q"].ToString();
            if(query.Length>200)return Results.BadRequest(new {error="Search text must be at most 200 characters."});
            var paged=parameters.ContainsKey("page")||parameters.ContainsKey("pageSize");
            var page=1;var pageSize=100;
            if(parameters.ContainsKey("page")&&(!int.TryParse(parameters["page"],NumberStyles.None,CultureInfo.InvariantCulture,out page)||page<1||page>100000)
                ||parameters.ContainsKey("pageSize")&&(!int.TryParse(parameters["pageSize"],NumberStyles.None,CultureInfo.InvariantCulture,out pageSize)||pageSize<1||pageSize>100))
                return Results.BadRequest(new {error="Page must be 1–100000 and page size 1–100."});
            var hits=new List<(string Study,string Kind,string Id,SearchHit Hit)>();
            foreach(var study in state.Studies.Where(study=>access(state,identity(context),study))) {
                foreach(var item in study.Items.Where(item=>EvidenceRules.ItemAvailable(study,item.Id)&&(item.Title+" "+item.Body).Contains(query,StringComparison.OrdinalIgnoreCase)))
                    hits.Add((study.Id,item.Kind,item.Id,new(study.Id,study.Title,item)));
                foreach(var file in study.Files.Where(file=>!file.Deleted&&(file.ParentId is null||EvidenceRules.ItemAvailable(study,file.ParentId))&&file.Name.Contains(query,StringComparison.OrdinalIgnoreCase)))
                    hits.Add((study.Id,"file",file.Id,new(study.Id,study.Title,new {id=file.Id,kind="file",title=file.Name,body="File version "+file.Version+" · "+file.Status})));
            }
            var total=hits.Count;
            var offset=(page-1)*pageSize;
            var items=hits.OrderBy(hit=>hit.Study,StringComparer.Ordinal).ThenBy(hit=>hit.Kind,StringComparer.Ordinal).ThenBy(hit=>hit.Id,StringComparer.Ordinal)
                .Skip(offset).Take(pageSize).Select(hit=>hit.Hit).ToArray();
            var hasMore=offset+items.Length<total;
            context.Response.Headers["X-Total-Count"]=total.ToString(CultureInfo.InvariantCulture);
            context.Response.Headers["X-Results-Truncated"]=(paged?hasMore:total>100)?"true":"false";
            return paged?Results.Ok(new {items,total,page,pageSize,hasMore}):Results.Ok(items);
        }));
    }
}
