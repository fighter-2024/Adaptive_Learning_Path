-- M9：非破坏性缓存元数据；旧报告摘要为空摘要时自动失效重算。
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF OBJECT_ID('dbo.weekly_reports', 'U') IS NULL
    THROW 51003, 'weekly_reports table is required', 1;
IF COL_LENGTH('dbo.weekly_reports', 'source_digest') IS NULL
    ALTER TABLE dbo.weekly_reports ADD source_digest VARCHAR(64) NULL;
IF COL_LENGTH('dbo.weekly_reports', 'degraded') IS NULL
    ALTER TABLE dbo.weekly_reports ADD degraded BIT NOT NULL
        CONSTRAINT DF_weekly_reports_degraded DEFAULT 1;
IF COL_LENGTH('dbo.weekly_reports', 'degraded_reason') IS NULL
    ALTER TABLE dbo.weekly_reports ADD degraded_reason NVARCHAR(200) NULL;
COMMIT TRANSACTION;
