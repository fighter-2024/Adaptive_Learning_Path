-- Migration 0002: 为诊断会话补齐 DINA 可追踪字段。
-- 仅增加可空/带默认值的列，不覆盖既有诊断结果。

IF OBJECT_ID('dbo.diagnosis_sessions', 'U') IS NULL
    THROW 51002, '缺少 diagnosis_sessions 表，请先执行一次性空库初始化 init.sql。', 1;
GO

IF COL_LENGTH('dbo.diagnosis_sessions', 'algorithm_version') IS NULL
    ALTER TABLE dbo.diagnosis_sessions
        ADD algorithm_version VARCHAR(32) NOT NULL
            CONSTRAINT DF_diagnosis_sessions_algorithm_version DEFAULT 'dina-v1';
IF COL_LENGTH('dbo.diagnosis_sessions', 'parameter_version') IS NULL
    ALTER TABLE dbo.diagnosis_sessions
        ADD parameter_version VARCHAR(32) NOT NULL
            CONSTRAINT DF_diagnosis_sessions_parameter_version DEFAULT 'default-v1';
IF COL_LENGTH('dbo.diagnosis_sessions', 'answer_time_from') IS NULL
    ALTER TABLE dbo.diagnosis_sessions ADD answer_time_from DATETIME NULL;
IF COL_LENGTH('dbo.diagnosis_sessions', 'answer_time_to') IS NULL
    ALTER TABLE dbo.diagnosis_sessions ADD answer_time_to DATETIME NULL;
IF COL_LENGTH('dbo.diagnosis_sessions', 'repeat_strategy') IS NULL
    ALTER TABLE dbo.diagnosis_sessions
        ADD repeat_strategy VARCHAR(32) NOT NULL
            CONSTRAINT DF_diagnosis_sessions_repeat_strategy DEFAULT 'latest_attempt';
IF COL_LENGTH('dbo.diagnosis_sessions', 'converged') IS NULL
    ALTER TABLE dbo.diagnosis_sessions
        ADD converged BIT NOT NULL
            CONSTRAINT DF_diagnosis_sessions_converged DEFAULT 0;
IF COL_LENGTH('dbo.diagnosis_sessions', 'iterations') IS NULL
    ALTER TABLE dbo.diagnosis_sessions
        ADD iterations INT NOT NULL
            CONSTRAINT DF_diagnosis_sessions_iterations DEFAULT 0;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_diagnosis_sessions_iterations_nonnegative'
)
    ALTER TABLE dbo.diagnosis_sessions
        ADD CONSTRAINT CK_diagnosis_sessions_iterations_nonnegative
        CHECK (iterations >= 0);
GO
