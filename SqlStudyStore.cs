using System.Data;
using System.Data.Common;
using System.Text;
using System.Text.Json;
using Microsoft.Data.SqlClient;

/// <summary>Bounded single-row SQL snapshot adapter. No startup DDL or seed data.</summary>
public sealed class SqlStudyStore : IStudyStore
{
    public const int SchemaVersion = 1;
    public const int MaximumSnapshotBytes = 8 * 1024 * 1024;
    readonly Func<DbConnection> connectionFactory;
    static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    public SqlStudyStore(string connectionString)
    {
        if (string.IsNullOrWhiteSpace(connectionString))
            throw new InvalidOperationException("HUB_SQL_CONNECTION is required for SqlServer storage.");
        SqlConnectionStringBuilder configuration;
        try { configuration = new(connectionString); }
        catch (ArgumentException) { throw new InvalidOperationException("Invalid SQL storage configuration."); }
        if (string.IsNullOrWhiteSpace(configuration.DataSource) || string.IsNullOrWhiteSpace(configuration.InitialCatalog)
            || !string.IsNullOrEmpty(configuration.AttachDBFilename) || configuration.UserInstance
            || configuration.TrustServerCertificate || configuration.Encrypt == SqlConnectionEncryptOption.Optional
            || configuration.PersistSecurityInfo)
            throw new InvalidOperationException("SQL storage requires a database, encrypted certificate-validated connection, and no attached files or persisted credentials.");
        configuration.ConnectRetryCount = 0; // Do not replay ambiguous operations automatically.
        configuration.ConnectTimeout = 15;
        var validated = configuration.ConnectionString;
        connectionFactory = () => new SqlConnection(validated);
    }

    // Protocol-test seam: the caller supplies a connection, never a serialized identity or a membership roster.
    internal SqlStudyStore(Func<DbConnection> factory) => connectionFactory = factory;

    public T Read<T>(Func<State, T> read)
    {
        try
        {
            using var connection = connectionFactory();
            connection.Open();
            var snapshot = Load(connection, null, false);
            return read(snapshot.State); // A new object graph is deserialized for every operation.
        }
        catch (DbException) { throw new InvalidOperationException("SQL storage operation failed; verify database availability and schema through approved operator tools."); }
    }

    public IResult Change(Func<State, IResult> change)
    {
        try
        {
            using var connection = connectionFactory();
            connection.Open();
            using var transaction = connection.BeginTransaction(IsolationLevel.Serializable);
            var snapshot = Load(connection, transaction, true);
            var result = change(snapshot.State);
            if (result is not IStatusCodeHttpResult { StatusCode: >= 200 and < 300 })
            {
                transaction.Rollback();
                return result;
            }
            Save(connection, transaction, snapshot.State, snapshot.Revision);
            transaction.Commit();
            return result;
        }
        catch (DbException) { throw new InvalidOperationException("SQL storage operation failed; no success is confirmed. Retry through the original request identifier after operator verification."); }
    }

    /// <summary>Explicit command-line-only development import, never called on startup or from an HTTP route.</summary>
    public void InitializeSyntheticDemo(string environmentName, bool explicitSyntheticImport)
    {
        if (environmentName != Environments.Development || !explicitSyntheticImport)
            throw new InvalidOperationException("Synthetic SQL initialization requires Development and explicit synthetic import.");
        try
        {
            using var connection = connectionFactory();
            connection.Open();
            using var transaction = connection.BeginTransaction(IsolationLevel.Serializable);
            var snapshot = Load(connection, transaction, true);
            if (snapshot.Revision != 0 || snapshot.State.Studies.Count != 0 || snapshot.State.Roles.Count != 0 || snapshot.State.Audit.Count != 0)
                throw new InvalidOperationException("Synthetic initialization requires an untouched empty database snapshot.");
            Save(connection, transaction, Demo.Seed(), snapshot.Revision);
            transaction.Commit();
        }
        catch (DbException) { throw new InvalidOperationException("Synthetic SQL initialization failed; verify state before retrying."); }
    }

    static (State State, long Revision) Load(DbConnection connection, DbTransaction? transaction, bool forUpdate)
    {
        using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandTimeout = 30;
        command.CommandText = "SELECT SchemaVersion, Revision, StateJson FROM dbo.HubSnapshot "
            + (forUpdate ? "WITH (UPDLOCK, HOLDLOCK) " : "") + "WHERE SingletonId = 1;";
        using var reader = command.ExecuteReader(CommandBehavior.SingleRow);
        if (!reader.Read() || reader.GetInt32(0) != SchemaVersion)
            throw new InvalidOperationException("SQL schema is not initialized or has an unsupported version. Run the reviewed schema script explicitly.");
        var revision = reader.GetInt64(1);
        var json = reader.GetString(2);
        if (revision < 0 || Encoding.UTF8.GetByteCount(json) > MaximumSnapshotBytes)
            throw new InvalidDataException("SQL snapshot is invalid or exceeds the bounded preview limit.");
        try
        {
            using var document = JsonDocument.Parse(json);
            // Require explicit roles: State's demo constructor default must never create an admin from missing data.
            foreach (var property in new[] { "studies", "roles", "audit" })
                if (!document.RootElement.TryGetProperty(property, out var value) || value.ValueKind == JsonValueKind.Null)
                    throw new InvalidDataException("SQL snapshot is missing explicit required collections.");
            var state = JsonSerializer.Deserialize<State>(json, Json) ?? throw new InvalidDataException("SQL snapshot is empty.");
            return (state, revision);
        }
        catch (JsonException) { throw new InvalidDataException("SQL snapshot is not valid application JSON."); }
    }

    static void Save(DbConnection connection, DbTransaction transaction, State state, long revision)
    {
        var json = JsonSerializer.Serialize(state, Json);
        if (Encoding.UTF8.GetByteCount(json) > MaximumSnapshotBytes)
            throw new InvalidOperationException("SQL snapshot exceeds the bounded 8 MiB preview limit.");
        using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandTimeout = 30;
        command.CommandText = "UPDATE dbo.HubSnapshot SET StateJson = @state, Revision = Revision + 1, UpdatedAt = SYSUTCDATETIME() "
            + "WHERE SingletonId = 1 AND SchemaVersion = @schema AND Revision = @revision;";
        Add(command, "@state", DbType.String, json, -1);
        Add(command, "@schema", DbType.Int32, SchemaVersion);
        Add(command, "@revision", DbType.Int64, revision);
        if (command.ExecuteNonQuery() != 1)
            throw new InvalidOperationException("SQL snapshot concurrency conflict; no success is confirmed.");
    }

    static void Add(DbCommand command, string name, DbType type, object value, int? size = null)
    {
        var parameter = command.CreateParameter();
        parameter.ParameterName = name;
        parameter.DbType = type;
        parameter.Value = value;
        if (size.HasValue) parameter.Size = size.Value;
        command.Parameters.Add(parameter);
    }
}
