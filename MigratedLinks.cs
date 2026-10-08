using System.Text.Json;

public static class MigratedLinkEndpoints
{
    public static void MapMigratedLinkEndpoints(this WebApplication app,Func<HttpContext,string> identity,Func<State,string,Study,bool> access)
    {
        app.MapGet("/api/resolve",(HttpContext context,IStudyStore store,AttachmentStorage storage)=>store.Read<IResult>(state=> {
            var query=context.Request.Query;
            if(query.Any(p=>!new[]{"studyId","sourceStudyId","sourceId","sourceUrl"}.Contains(p.Key)||p.Value.Count!=1))
                return Results.BadRequest(new {error="Use one destination study and either a source identity pair or exact source URL."});
            var studyId=query["studyId"].ToString();var sourceStudy=query["sourceStudyId"].ToString();
            var sourceId=query["sourceId"].ToString();var sourceUrl=query["sourceUrl"].ToString();
            var urlMode=query.ContainsKey("sourceUrl");
            if(!Bounded(studyId,100)||urlMode&&(query.ContainsKey("sourceStudyId")||query.ContainsKey("sourceId")||!Bounded(sourceUrl,2000)||
                !Uri.TryCreate(sourceUrl,UriKind.Absolute,out var uri)||uri.Scheme is not ("http" or "https")||string.IsNullOrEmpty(uri.Host)||!string.IsNullOrEmpty(uri.UserInfo))||
                !urlMode&&(!Bounded(sourceStudy,200)||!Bounded(sourceId,200)))
                return Results.BadRequest(new {error="Provide a destination study and bounded source identifiers, or an exact HTTP(S) source URL without credentials. Source URLs are not fetched."});
            var study=state.Studies.FirstOrDefault(s=>s.Id==studyId&&access(state,identity(context),s));
            if(study is null)return Unavailable();
            // Match only within the already-authorized destination. Do not normalize away source version/query identity.
            var matches=study.ImportLedger.Values.Where(entry=>entry is not null&&entry.Source is not null&&(urlMode?LegacyUrl(entry.Source)==sourceUrl:
                entry.SourceStudyId==sourceStudy&&entry.SourceId==sourceId)).ToArray();
            if(matches.Length!=1||matches[0].Deleted)return Unavailable();
            var match=matches[0];
            if(match.Source.SourceStudyId!=match.SourceStudyId||match.Source.SourceId!=match.SourceId)return Unavailable();
            var item=study.Items.FirstOrDefault(item=>item.Id==match.TargetId&&EvidenceRules.ItemAvailable(study,item.Id));
            if(item is not null) {
                if(item.Provenance?.SourceStudyId!=match.SourceStudyId||item.Provenance.SourceId!=match.SourceId)return Unavailable();
                var view=item.Kind switch {"decision" or "task"=>"task","reply"=>"discussion","resource"=>"documentation",_=>item.Kind};
                if(!new[]{"document","documentation","discussion","task","idea"}.Contains(view))return Unavailable();
                var route=Route(study.Id,view,item.Id);
                if(item.BoardIdea is {} idea)route=$"#study/{Uri.EscapeDataString(study.Id)}/idea/board-{Uri.EscapeDataString(idea.BoardId)}/{Uri.EscapeDataString(item.Id)}";
                return Results.Ok(new {href=route,item.Title,item.Kind,item.Version,studyId=study.Id,sourceStudyId=match.SourceStudyId,sourceId=match.SourceId});
            }
            var file=study.Files.FirstOrDefault(file=>file.Id==match.TargetId&&EvidenceRules.FileAvailable(study,file.Id,storage));
            if(file is null||file.Provenance?.SourceStudyId!=match.SourceStudyId||file.Provenance.SourceId!=match.SourceId)return Unavailable();
            return Results.Ok(new {href=Route(study.Id,"document",file.Id),title=file.Name,kind="file",file.Version,studyId=study.Id,sourceStudyId=match.SourceStudyId,sourceId=match.SourceId});
        }));
    }
    static string? LegacyUrl(SourceProvenance source)=>source.Original.ValueKind==JsonValueKind.Object&&source.Original.TryGetProperty("legacy_url",out var value)&&value.ValueKind==JsonValueKind.String?value.GetString():null;
    static bool Bounded(string value,int maximum)=>!string.IsNullOrWhiteSpace(value)&&value.Length<=maximum&&!value.Any(char.IsControl);
    static IResult Unavailable()=>Results.NotFound(new {error="No available migrated record matches this link in the selected study."});
    static string Route(string study,string view,string id)=>$"#study/{Uri.EscapeDataString(study)}/{view}/{Uri.EscapeDataString(id)}";
}
