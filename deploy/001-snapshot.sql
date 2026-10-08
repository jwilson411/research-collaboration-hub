-- Explicit reviewed initialization against a separately provisioned empty database.
-- No database creation, login creation, grants, migrations-on-startup, or demo seeding.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF OBJECT_ID(N'dbo.HubSnapshot', N'U') IS NOT NULL
    THROW 51000, 'HubSnapshot already exists; verify the existing schema rather than overwriting it.', 1;
CREATE TABLE dbo.HubSnapshot (
    SingletonId tinyint NOT NULL CONSTRAINT PK_HubSnapshot PRIMARY KEY,
    SchemaVersion int NOT NULL,
    Revision bigint NOT NULL,
    StateJson nvarchar(max) NOT NULL,
    UpdatedAt datetime2(7) NOT NULL CONSTRAINT DF_HubSnapshot_UpdatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_HubSnapshot_Singleton CHECK (SingletonId = 1),
    CONSTRAINT CK_HubSnapshot_Schema CHECK (SchemaVersion = 1),
    CONSTRAINT CK_HubSnapshot_Revision CHECK (Revision >= 0),
    CONSTRAINT CK_HubSnapshot_Json CHECK (ISJSON(StateJson) = 1)
);
INSERT dbo.HubSnapshot (SingletonId, SchemaVersion, Revision, StateJson)
VALUES (1, 1, 0, N'{"studies":[],"roles":{},"audit":[]}');
COMMIT TRANSACTION;
