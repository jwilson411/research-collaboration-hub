using System.Security.Cryptography;

// Local synthetic identity selection only. Production startup remains disabled.
// Session state is deliberately memory-only: restart invalidates every outstanding context.
public sealed class DemoSessionStore
{
    public const string CookieName="hub.session";
    public const string HeaderName="X-HUB-SESSION";
    public const int MaximumSessions=1024;
    static readonly TimeSpan IdleLifetime=TimeSpan.FromHours(8);
    readonly object gate=new();
    readonly Dictionary<string,Entry> sessions=new(StringComparer.Ordinal);
    public sealed class Entry
    {
        public readonly SemaphoreSlim Serial=new(1,1);
        public string Actor="alex";
        public string Generation=OpaqueToken();
        public DateTimeOffset LastUsed=DateTimeOffset.UtcNow;
        public int Users;
    }
    public sealed record RequestContext(Entry Session,string Actor);
    static readonly object ContextKey=new();
    static string OpaqueToken()=>Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
    static bool IsToken(string? token)=>token is {Length:64}&&token.All(character=>character is >= '0' and <= '9' or >= 'A' and <= 'F');
    public static string Actor(HttpContext context)=>Context(context).Actor;
    public static string Generation(HttpContext context)=>Context(context).Session.Generation;
    static RequestContext Context(HttpContext context)=>context.Items[ContextKey] as RequestContext??throw new InvalidOperationException("A server session context is required.");
    public static void Switch(HttpContext context,string actor)
    {
        var entry=Context(context).Session;
        entry.Actor=actor;
        entry.Generation=OpaqueToken();
        context.Response.Headers[HeaderName]=entry.Generation;
    }
    static Task Changed(HttpContext context)
    {
        context.Response.StatusCode=409;
        return context.Response.WriteAsJsonAsync(new {code="session_changed",error="Your demo session changed or expired. Refresh the session and review the intended identity before trying again."});
    }
    public async Task Invoke(HttpContext context,RequestDelegate next)
    {
        if(!context.Request.Path.StartsWithSegments("/api")){await next(context);return;}
        var mutation=context.Request.Method is not ("GET" or "HEAD" or "OPTIONS");
        var refreshing=context.Request.Method=="GET"&&context.Request.Path.Equals("/api/session");
        Entry? entry=null;
        string? newCookie=null;
        var now=DateTimeOffset.UtcNow;
        lock(gate)
        {
            var cookie=context.Request.Cookies[CookieName];
            if(IsToken(cookie)&&sessions.TryGetValue(cookie!,out var found))
            {
                if(found.Users==0&&now-found.LastUsed>=IdleLifetime)sessions.Remove(cookie!);
                else entry=found;
            }
            // A mutation with an unknown/expired cookie cannot silently establish Alex.
            if(entry is null&&!mutation)
            {
                foreach(var key in sessions.Where(pair=>pair.Value.Users==0&&now-pair.Value.LastUsed>=IdleLifetime).Select(pair=>pair.Key).ToArray())sessions.Remove(key);
                if(sessions.Count<MaximumSessions)
                {
                    newCookie=OpaqueToken();entry=new();sessions.Add(newCookie,entry);
                }
            }
            if(entry is not null)entry.Users++;
        }
        if(entry is null)
        {
            if(mutation){await Changed(context);return;}
            context.Response.StatusCode=503;
            await context.Response.WriteAsJsonAsync(new {error="Local demo session capacity is reached. Restart the demo or wait for idle sessions to expire."});return;
        }
        var acquired=false;
        try
        {
            await entry.Serial.WaitAsync(context.RequestAborted);acquired=true;
            if(newCookie is not null)context.Response.Cookies.Append(CookieName,newCookie,new CookieOptions {HttpOnly=true,SameSite=SameSiteMode.Strict,IsEssential=true,Path="/"});
            context.Items[ContextKey]=new RequestContext(entry,entry.Actor);
            context.Response.Headers[HeaderName]=entry.Generation;
            var supplied=context.Request.Headers[HeaderName];
            if((mutation||(!refreshing&&supplied.Count>0))&&(supplied.Count!=1||!IsToken(supplied[0])||!CryptographicOperations.FixedTimeEquals(System.Text.Encoding.ASCII.GetBytes(supplied[0]!),System.Text.Encoding.ASCII.GetBytes(entry.Generation))))
            {await Changed(context);return;}
            await next(context);
        }
        finally
        {
            context.Items.Remove(ContextKey);
            if(acquired)entry.Serial.Release();
            lock(gate){entry.Users--;entry.LastUsed=DateTimeOffset.UtcNow;}
        }
    }
}
