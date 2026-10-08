using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Antiforgery;

var builder = WebApplication.CreateBuilder(args);
if (!builder.Environment.IsDevelopment() || Environment.GetEnvironmentVariable("HUB_DEMO_ENABLED") != "true") throw new InvalidOperationException("Demo provider is Development-only. Production identity and storage adapters require implementation and validation.");
builder.WebHost.UseUrls("http://127.0.0.1:5080");
builder.Services.AddSingleton<AttachmentStorage>();
builder.Services.AddAntiforgery(o => { o.HeaderName = "X-CSRF-TOKEN"; o.Cookie.Name = "hub.csrf"; o.Cookie.SameSite = SameSiteMode.Strict; });
var provider=Environment.GetEnvironmentVariable("HUB_STORAGE_PROVIDER") ?? "Json";
if(provider is not ("Json" or "SqlServer"))throw new InvalidOperationException("Unknown storage provider.");
builder.Services.AddSingleton<IStudyStore>(_ => provider switch {
 "Json" => new JsonStudyStore(Environment.GetEnvironmentVariable("HUB_DATA") ?? Path.Combine(builder.Environment.ContentRootPath, ".data", "hub.json")),
 "SqlServer" => new SqlStudyStore(Environment.GetEnvironmentVariable("HUB_SQL_CONNECTION") ?? ""),
 _ => throw new InvalidOperationException("Unknown storage provider.")
});
builder.Services.ConfigureHttpJsonOptions(options => {
 var resolver=new System.Text.Json.Serialization.Metadata.DefaultJsonTypeInfoResolver();
 resolver.Modifiers.Add(info => {
 if(info.Type==typeof(SourceProvenance)) {var original=info.Properties.FirstOrDefault(p=>p.Name=="original");if(original is not null)original.ShouldSerialize=(_,_)=>false;}
 if(info.Type==typeof(State)) {var requests=info.Properties.FirstOrDefault(p=>p.Name=="configRequests");if(requests is not null)requests.ShouldSerialize=(_,_)=>false;}
 if(info.Type==typeof(Study)) {
  foreach(var name in new[]{"requests","importLedger","importReports","handoffs"}) {var hidden=info.Properties.FirstOrDefault(p=>p.Name==name);if(hidden is not null)hidden.ShouldSerialize=(_,_)=>false;}
  var reviews=info.Properties.FirstOrDefault(p=>p.Name=="documentReviews"); if(reviews is not null)reviews.Get=obj=>{var study=(Study)obj;return study.DocumentReviews.Where(pair=>study.Items.Any(item=>item.Id==pair.Key&&!item.Deleted&&item.Kind=="document")).ToDictionary(pair=>pair.Key,pair=>pair.Value);};
  var files=info.Properties.FirstOrDefault(p=>p.Name=="files"); if(files is not null)files.Get=obj=>{ var study=(Study)obj; return study.Files.Where(file=>!file.Deleted&&(file.ParentId is null||EvidenceRules.ItemAvailable(study,file.ParentId))).ToList(); };
 } });
 options.SerializerOptions.TypeInfoResolver=resolver;
});
var app = builder.Build();
if(args.Contains("--initialize-synthetic-sql")) {
 if(provider!="SqlServer")throw new InvalidOperationException("Explicit SQL initialization requires SqlServer provider.");
 ((SqlStudyStore)app.Services.GetRequiredService<IStudyStore>()).InitializeSyntheticDemo(builder.Environment.EnvironmentName,Environment.GetEnvironmentVariable("HUB_DEMO_ENABLED")=="true");
 return;
}
app.Use(async (ctx, next) => {
 if (ctx.Connection.RemoteIpAddress is not { } ip || !IPAddress.IsLoopback(ip) || !(ctx.Request.Host.Host is "127.0.0.1" or "localhost" or "::1")) { ctx.Response.StatusCode=403; return; }
 ctx.Response.Headers["X-Content-Type-Options"]="nosniff";
 ctx.Response.Headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'";
 ctx.Response.Headers["Cache-Control"]="no-store";
 ctx.Features.Get<Microsoft.AspNetCore.Http.Features.IHttpMaxRequestBodySizeFeature>()!.MaxRequestBodySize = 1048576;
 if (ctx.Request.ContentLength > 1048576) { ctx.Response.StatusCode=413; return; }
 if (ctx.Request.Method is not ("GET" or "HEAD" or "OPTIONS")) {
  try { await ctx.RequestServices.GetRequiredService<IAntiforgery>().ValidateRequestAsync(ctx); }
  catch (AntiforgeryValidationException) { ctx.Response.StatusCode=400; await ctx.Response.WriteAsJsonAsync(new {error="Invalid anti-forgery token. Refresh and retry."}); return; }
 }
 try { await next(); } catch (BadHttpRequestException) { ctx.Response.StatusCode=400; } catch (JsonException) { ctx.Response.StatusCode=400; }
});
app.UseDefaultFiles(); app.UseStaticFiles();
string Identity(HttpContext c) => c.Request.Cookies["hub.identity"] is string id && Demo.Identities.Any(x=>x.Id==id) ? id : "alex";
bool Access(State state,string user,Study study) => Demo.Groups.GetValueOrDefault(user, []).Contains(study.GroupId);
bool Admin(State state,string user) => state.Roles.GetValueOrDefault(user)=="Administrator";
app.MapGet("/api/session", (HttpContext c,IAntiforgery anti,IStudyStore store) => store.Read(s=>new {user=new {id=Identity(c),name=Demo.Identities.Single(x=>x.Id==Identity(c)).Name,role=s.Roles.GetValueOrDefault(Identity(c),"Researcher")},identities=Demo.Identities,csrf=anti.GetAndStoreTokens(c).RequestToken}));
app.MapPost("/api/session", (HttpContext c,SessionInput input) => {
 if (!Demo.Identities.Any(x=>x.Id==input.Identity)) return Results.BadRequest(new {error="Unknown synthetic identity"});
 c.Response.Cookies.Append("hub.identity",input.Identity,new CookieOptions {HttpOnly=true,SameSite=SameSiteMode.Strict,IsEssential=true}); return Results.Ok();
});
app.MapGet("/api/studies",(HttpContext c,IStudyStore store)=>store.Read(s=>s.Studies.Where(x=>Access(s,Identity(c),x)).ToArray()));
app.MapGet("/api/studies/{id}",(string id,HttpContext c,IStudyStore store)=>store.Read<IResult>(s=>s.Studies.FirstOrDefault(x=>x.Id==id && Access(s,Identity(c),x)) is {} study ? Results.Ok(study) : Results.NotFound()));
app.MapGet("/api/search",(string? q,HttpContext c,IStudyStore store)=>store.Read<IResult>(s=> {
 if(q?.Length>200)return Results.BadRequest();
 var query=q??"";
 var hits=new List<object>();
 foreach(var study in s.Studies.Where(study=>Access(s,Identity(c),study))) {
  hits.AddRange(study.Items.Where(item=>!item.Deleted&&(item.Title+" "+item.Body).Contains(query,StringComparison.OrdinalIgnoreCase)).Select(item=>(object)new {studyId=study.Id,studyTitle=study.Title,item}));
  hits.AddRange(study.Files.Where(file=>!file.Deleted&&(file.ParentId is null||EvidenceRules.ItemAvailable(study,file.ParentId))&&file.Name.Contains(query,StringComparison.OrdinalIgnoreCase)).Select(file=>(object)new {studyId=study.Id,studyTitle=study.Title,item=new {id=file.Id,kind="file",title=file.Name,body="File version "+file.Version+" · "+file.Status}}));
 }
 return Results.Ok(hits.Take(100));
}));
app.MapPost("/api/studies/{id}/items",(string id,ItemInput input,HttpContext c,IStudyStore store,AttachmentStorage storage)=>store.Change(s=> {
 var study=s.Studies.FirstOrDefault(x=>x.Id==id && Access(s,Identity(c),x)); if(study is null)return Results.NotFound();
 if (!Guid.TryParse(input.RequestId,out _) || !new[]{"document","documentation","discussion","reply","decision","idea"}.Contains(input.Kind) || string.IsNullOrWhiteSpace(input.Title) || input.Title.Length>180 || string.IsNullOrWhiteSpace(input.Body) || input.Body.Length>20000) return Results.BadRequest(new {error="Provide a valid kind, title (1–180), body (1–20000), and request identifier."});
 var fingerprint=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(input))));
 if(study.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(study):Results.Conflict(new {error="Request identifier was already used for a different operation."});
 if(study.Revision!=input.ExpectedRevision)return Results.Conflict(new {error="Study changed. Refresh before retrying; your text has not been saved."});
 if(study.Stage!="Active")return Results.Conflict(new {error="Reopen the study before making changes."});
 if(input.ParentId is not null && !study.Items.Any(i=>i.Id==input.ParentId&&!i.Deleted && (input.Kind!="reply" || i.Kind is "discussion" or "reply")))return Results.BadRequest(new {error="Parent must be a live record in this study; replies require a discussion or reply."});
 if(input.Kind=="reply" && input.ParentId is null)return Results.BadRequest(new {error="Replies require a parent."});
 if(input.DocumentId is not null && !study.Items.Any(i=>i.Id==input.DocumentId&&!i.Deleted&&i.Kind=="document"))return Results.BadRequest(new {error="Evidence must be a live document version in this study."});
 var fileIds=input.FileIds??[];
 if(fileIds.Length>30||fileIds.Distinct().Count()!=fileIds.Length||fileIds.Any(fileId=>!EvidenceRules.FileAvailable(study,fileId,storage)))return Results.BadRequest(new {error="File evidence must reference distinct released versions in this study."});
 var item=new Item(Guid.NewGuid().ToString(),input.Kind,input.Title.Trim(),input.Body,input.ParentId,input.DocumentId,input.Kind=="document"?1:study.Items.Count(i=>i.Kind==input.Kind&&i.Title==input.Title.Trim())+1,Identity(c),DateTimeOffset.UtcNow){FileIds=fileIds};
 study.Items.Add(item); study.Requests.Add(input.RequestId,fingerprint); study.Revision++; s.Audit.Add(new(Identity(c),"Created "+input.Kind,study.Id,DateTimeOffset.UtcNow)); return Results.Ok(study);
}));
app.MapPost("/api/studies/{id}/stage",(string id,StageInput input,HttpContext c,IStudyStore store)=>store.Change(s=> {
 var st=s.Studies.FirstOrDefault(x=>x.Id==id&&Access(s,Identity(c),x));if(st is null)return Results.NotFound();
 if(!Guid.TryParse(input.RequestId,out _)||!new[]{"Active","Paused","Closed"}.Contains(input.Stage))return Results.BadRequest();
 var fingerprint=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(input))));
 if(st.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(st):Results.Conflict();
 if(st.Revision!=input.ExpectedRevision)return Results.Conflict();
 st.Stage=input.Stage;st.Revision++;st.Requests.Add(input.RequestId,fingerprint);s.Audit.Add(new(Identity(c),"Lifecycle: "+input.Stage,id,DateTimeOffset.UtcNow));return Results.Ok(st);
}));
app.MapGet("/api/studies/{id}/documents/{itemId}/download",(string id,string itemId,HttpContext c,IStudyStore store)=>store.Read<IResult>(s=> {
 var st=s.Studies.FirstOrDefault(x=>x.Id==id&&Access(s,Identity(c),x));var item=st?.Items.FirstOrDefault(i=>i.Id==itemId&&!i.Deleted&&i.Kind=="document");
 return item is null?Results.NotFound():Results.File(Encoding.UTF8.GetBytes(item.Body),"text/plain",$"document-{item.Id}.txt");
}));
app.MapPost("/api/studies/{id}/items/{itemId}/delete",(string id,string itemId,RevisionInput input,HttpContext c,IStudyStore store)=>store.Change(s=> {
 var st=s.Studies.FirstOrDefault(x=>x.Id==id&&Access(s,Identity(c),x));if(st is null)return Results.NotFound();
 if(!Guid.TryParse(input.RequestId,out _))return Results.BadRequest();
 var document=st.Items.FirstOrDefault(item=>item.Id==itemId&&item.Kind=="document"&&!item.Deleted);
 if(document is not null&&DocumentRules.DeletionError(st,document,Identity(c)) is {} deletionError)return Results.Conflict(new {error=deletionError});
 var fingerprint=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("delete:"+itemId+":"+JsonSerializer.Serialize(input))));
 if(st.Requests.TryGetValue(input.RequestId,out var prior))return prior==fingerprint?Results.Ok(st):Results.Conflict();
 if(st.Revision!=input.ExpectedRevision||st.Stage!="Active")return Results.Conflict();
 if(st.CurrentProtocol is {Kind:"item"} protocol&&protocol.Id==itemId)return Results.Conflict(new {error="Choose another current protocol or clear its designation before removing this version."});
 if(st.Files.Any(file=>!file.Deleted&&EvidenceRules.HasAncestor(st,file.ParentId,itemId)&&EvidenceRules.ProtectedByAcceptedDocument(st,file.Id)))return Results.Conflict(new {error="An accepted document retains an attachment on this record as evidence."});
 var importedParent=st.ImportLedger.Values.FirstOrDefault(entry=>entry.TargetId==itemId);
 if(importedParent is not null && (st.Items.Any(child=>!child.Deleted&&child.ParentId==itemId)||st.Files.Any(child=>!child.Deleted&&(child.ParentId==itemId||child.FamilyId==itemId))||st.ImportLedger.Values.Any(entry=>entry.SourceStudyId==importedParent.SourceStudyId && entry.Source.Original.ValueKind==JsonValueKind.Object && entry.Source.Original.TryGetProperty("parent_id",out var parent) && parent.ValueKind==JsonValueKind.String && parent.GetString()==importedParent.SourceId && (st.Items.Any(child=>child.Id==entry.TargetId&&!child.Deleted)||st.Files.Any(child=>child.Id==entry.TargetId&&!child.Deleted)))))return Results.Conflict(new {error="Remove imported child records first so historical structure cannot be silently broken."});
 var index=st.Items.FindIndex(i=>i.Id==itemId&&!i.Deleted);if(index<0)return Results.NotFound();
 st.Items[index]=st.Items[index] with {Deleted=true,Body="[Removed from demo view]",Task=null,FileIds=[],Provenance=null};st.Revision++;st.Requests.Add(input.RequestId,fingerprint);s.Audit.Add(new(Identity(c),"Removed item",st.Id,DateTimeOffset.UtcNow));return Results.Ok(st);
}));
app.MapDocumentEndpoints(Identity,Access);
app.MapHandoffEndpoints(Identity,Access);
app.MapAdminEndpoints(Identity,Access,Admin);
app.MapProtocolEndpoints(Identity,Access);
app.MapSyntheticImportEndpoints(Identity,Access);
app.MapTaskEndpoints(Identity,Access);
app.MapAttachmentEndpoints(Identity,Access);
app.MapFallbackToFile("index.html");app.Run();
record RevisionInput(int ExpectedRevision,string RequestId);
record SessionInput(string Identity);
record ItemInput(string Kind,string Title,string Body,string? ParentId,string? DocumentId,int ExpectedRevision,string RequestId,string[]? FileIds=null);
record StageInput(string Stage,int ExpectedRevision,string RequestId);
public record Item(string Id,string Kind,string Title,string Body,string? ParentId,string? DocumentId,int Version,string Author,DateTimeOffset CreatedAt,bool Deleted=false) { [System.Text.Json.Serialization.JsonIgnore(Condition=System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull)] public DocumentVersionDetails? DocumentVersion {get;init;} public TaskDetails? Task {get;init;} public string[] FileIds {get;init;}=[]; public SourceProvenance? Provenance {get;init;} }
public record Audit(string Actor,string Action,string Target,DateTimeOffset At);
public class Study {public string Id{get;set;}="";public string Title{get;set;}="";public string Summary{get;set;}="";public string Stage{get;set;}="Active";public string GroupId{get;set;}="";public int Revision{get;set;}=1;public List<Item> Items{get;set;}=[];public List<StoredFile> Files{get;set;}=[];public Dictionary<string,DocumentReviewState> DocumentReviews {get;set;}=[];public List<HandoffSnapshot> Handoffs {get;set;}=[];public ProtocolDesignation? CurrentProtocol {get;set;} public List<ProtocolDesignation> ProtocolHistory {get;set;}=[];public Dictionary<string,ImportEntry> ImportLedger {get;set;}=[];public List<ImportReport> ImportReports {get;set;}=[];public Dictionary<string,string> Requests{get;set;}=[];}
public class State {public int ConfigRevision {get;set;}=1;public Dictionary<string,string> ConfigRequests {get;set;}=[];public List<ConfigurationChange> ConfigurationHistory {get;set;}=[];public List<Study> Studies{get;set;}=[];public Dictionary<string,string> Roles{get;set;}=new(){{"admin","Administrator"}};public List<Audit> Audit{get;set;}=[];}
public interface IStudyStore { T Read<T>(Func<State,T> read); IResult Change(Func<State,IResult> change); }
public sealed class JsonStudyStore:IStudyStore {
 readonly string path;readonly object gate=new();State state;readonly JsonSerializerOptions json=new(JsonSerializerDefaults.Web){WriteIndented=true};
 public JsonStudyStore(string path){this.path=Path.GetFullPath(path);Directory.CreateDirectory(Path.GetDirectoryName(this.path)!);state=File.Exists(path)?JsonSerializer.Deserialize<State>(File.ReadAllText(path),json)??throw new InvalidDataException():Demo.Seed();}
 public T Read<T>(Func<State,T> read){lock(gate)return read(JsonSerializer.Deserialize<State>(JsonSerializer.Serialize(state,json),json)!);}
 public IResult Change(Func<State,IResult> change){lock(gate){var copy=JsonSerializer.Deserialize<State>(JsonSerializer.Serialize(state,json),json)!;var result=change(copy);if(result is Microsoft.AspNetCore.Http.IStatusCodeHttpResult status && status.StatusCode>=400)return result;var tmp=path+".tmp";File.WriteAllText(tmp,JsonSerializer.Serialize(copy,json));File.Move(tmp,path,true);state=copy;return result;}}
}
public static class Demo {

 public static readonly DemoIdentity[] Identities=[new("alex","Alex • synthetic researcher","Researcher"),new("sam","Sam • synthetic researcher","Researcher"),new("admin","Morgan • synthetic administrator","Administrator"),new("reviewer","Casey • synthetic reviewer","Researcher"),new("lead","Riley • synthetic study lead","Researcher")];
 public static readonly Dictionary<string,string[]> Groups=new(){{"alex",["demo-group-a"]},{"sam",["demo-group-b"]},{"admin",[]},{"reviewer",["demo-group-a"]},{"lead",["demo-group-a"]}};
 public static State Seed()=>SeedJourney.Apply(new(){Studies=[new(){Id="atlas",Title="Atlas • Research methods pilot",Summary="A synthetic workspace exploring reproducible research coordination and clear handoffs.",GroupId="demo-group-a",Items=[new("protocol-1","document","Current protocol","Synthetic protocol v1. Compare two documentation approaches using fictional observations only.",null,null,1,"alex",DateTimeOffset.Parse("2026-09-01T10:00:00Z")),new("orientation-1","documentation","Start here","Review the protocol, introduce your question, and record the next action. Alex is the synthetic study contact.",null,"protocol-1",1,"alex",DateTimeOffset.Parse("2026-09-01T10:00:00Z")),new("question-1","discussion","How should we structure the handoff?","Propose an outline that keeps assumptions and unresolved questions visible.",null,"protocol-1",1,"alex",DateTimeOffset.Parse("2026-09-02T10:00:00Z")),new("task-1","task","Review the draft protocol","Owner: Alex (synthetic). Next action: agree the documentation checklist.",null,"protocol-1",1,"alex",DateTimeOffset.Parse("2026-09-02T10:00:00Z"))]},new(){Id="beacon",Title="Beacon • Historical methods study",Summary="Synthetic historical workspace demonstrating reopening with retained context.",Stage="Paused",GroupId="demo-group-b",Items=[new("beacon-protocol","document","Historical protocol","Synthetic historical record retained for continuation.",null,null,1,"departed-synthetic-author",DateTimeOffset.Parse("2020-01-01T10:00:00Z"))]}]});
}
public record DemoIdentity(string Id,string Name,string Role);
