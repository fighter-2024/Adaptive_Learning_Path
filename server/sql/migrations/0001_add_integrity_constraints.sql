-- Migration 0001: 为初始化表补齐同库约束、检查和反向查询索引。
-- 约定：文件名为 NNNN_description.sql，由 server/sql/migrate.py 按序执行。
-- 本迁移不包含 DROP、清库或覆盖式重建；发现历史数据不满足约束时应回滚并人工修复。

IF OBJECT_ID('dbo.users', 'U') IS NULL
    THROW 51001, '缺少 users 表，请先执行一次性空库初始化 init.sql。', 1;
IF OBJECT_ID('dbo.chapters', 'U') IS NULL
    THROW 51001, '缺少 chapters 表，请先执行一次性空库初始化 init.sql。', 1;
IF OBJECT_ID('dbo.questions', 'U') IS NULL
    THROW 51001, '缺少 questions 表，请先执行一次性空库初始化 init.sql。', 1;
IF OBJECT_ID('dbo.q_matrix', 'U') IS NULL
    THROW 51001, '缺少 q_matrix 表，请先执行一次性空库初始化 init.sql。', 1;
IF OBJECT_ID('dbo.answer_records', 'U') IS NULL
    THROW 51001, '缺少 answer_records 表，请先执行一次性空库初始化 init.sql。', 1;
IF OBJECT_ID('dbo.diagnosis_sessions', 'U') IS NULL
    THROW 51001, '缺少 diagnosis_sessions 表，请先执行一次性空库初始化 init.sql。', 1;
IF OBJECT_ID('dbo.user_kp_mastery', 'U') IS NULL
    THROW 51001, '缺少 user_kp_mastery 表，请先执行一次性空库初始化 init.sql。', 1;
IF OBJECT_ID('dbo.check_ins', 'U') IS NULL
    THROW 51001, '缺少 check_ins 表，请先执行一次性空库初始化 init.sql。', 1;
IF OBJECT_ID('dbo.achievements', 'U') IS NULL
    THROW 51001, '缺少 achievements 表，请先执行一次性空库初始化 init.sql。', 1;
IF OBJECT_ID('dbo.user_achievements', 'U') IS NULL
    THROW 51001, '缺少 user_achievements 表，请先执行一次性空库初始化 init.sql。', 1;
IF OBJECT_ID('dbo.weekly_reports', 'U') IS NULL
    THROW 51001, '缺少 weekly_reports 表，请先执行一次性空库初始化 init.sql。', 1;
GO

-- 同库关系使用真实外键，默认 NO ACTION，避免删除父记录时静默级联丢数据。
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_chapters_parent')
    ALTER TABLE dbo.chapters
        ADD CONSTRAINT FK_chapters_parent
        FOREIGN KEY (parent_chapter_id) REFERENCES dbo.chapters(chapter_id);

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_q_matrix_question')
    ALTER TABLE dbo.q_matrix
        ADD CONSTRAINT FK_q_matrix_question
        FOREIGN KEY (question_id) REFERENCES dbo.questions(question_id);

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_answer_records_user')
    ALTER TABLE dbo.answer_records
        ADD CONSTRAINT FK_answer_records_user
        FOREIGN KEY (user_id) REFERENCES dbo.users(user_id);

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_answer_records_question')
    ALTER TABLE dbo.answer_records
        ADD CONSTRAINT FK_answer_records_question
        FOREIGN KEY (question_id) REFERENCES dbo.questions(question_id);

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_diagnosis_sessions_user')
    ALTER TABLE dbo.diagnosis_sessions
        ADD CONSTRAINT FK_diagnosis_sessions_user
        FOREIGN KEY (user_id) REFERENCES dbo.users(user_id);

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_user_kp_mastery_user')
    ALTER TABLE dbo.user_kp_mastery
        ADD CONSTRAINT FK_user_kp_mastery_user
        FOREIGN KEY (user_id) REFERENCES dbo.users(user_id);

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_check_ins_user')
    ALTER TABLE dbo.check_ins
        ADD CONSTRAINT FK_check_ins_user
        FOREIGN KEY (user_id) REFERENCES dbo.users(user_id);

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_user_achievements_user')
    ALTER TABLE dbo.user_achievements
        ADD CONSTRAINT FK_user_achievements_user
        FOREIGN KEY (user_id) REFERENCES dbo.users(user_id);

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_user_achievements_achievement')
    ALTER TABLE dbo.user_achievements
        ADD CONSTRAINT FK_user_achievements_achievement
        FOREIGN KEY (achievement_id) REFERENCES dbo.achievements(achievement_id);

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_weekly_reports_user')
    ALTER TABLE dbo.weekly_reports
        ADD CONSTRAINT FK_weekly_reports_user
        FOREIGN KEY (user_id) REFERENCES dbo.users(user_id);
GO

-- 数值边界约束，防止异常数据污染诊断和周报。
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_answer_records_time_spent_nonnegative')
    ALTER TABLE dbo.answer_records ADD CONSTRAINT CK_answer_records_time_spent_nonnegative
        CHECK (time_spent IS NULL OR time_spent >= 0);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_diagnosis_sessions_question_count_nonnegative')
    ALTER TABLE dbo.diagnosis_sessions ADD CONSTRAINT CK_diagnosis_sessions_question_count_nonnegative
        CHECK (question_count >= 0);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_user_kp_mastery_probability')
    ALTER TABLE dbo.user_kp_mastery ADD CONSTRAINT CK_user_kp_mastery_probability
        CHECK (mastery_probability >= 0.0 AND mastery_probability <= 1.0);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_user_kp_mastery_counts')
    ALTER TABLE dbo.user_kp_mastery ADD CONSTRAINT CK_user_kp_mastery_counts
        CHECK (questions_done >= 0 AND correct_count >= 0 AND correct_count <= questions_done);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_check_ins_streak_nonnegative')
    ALTER TABLE dbo.check_ins ADD CONSTRAINT CK_check_ins_streak_nonnegative
        CHECK (streak_days >= 0);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_weekly_reports_dates')
    ALTER TABLE dbo.weekly_reports ADD CONSTRAINT CK_weekly_reports_dates
        CHECK (week_end >= week_start);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_weekly_reports_counts_nonnegative')
    ALTER TABLE dbo.weekly_reports ADD CONSTRAINT CK_weekly_reports_counts_nonnegative
        CHECK (questions_done >= 0 AND study_time_minutes >= 0);
GO

-- 跨库知识点 ID 不建立物理外键，由 kg-data/scripts/verify_cross_store_ids.py 校验。
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('dbo.q_matrix') AND name = 'IX_q_matrix_knowledge_point_id'
)
    CREATE NONCLUSTERED INDEX IX_q_matrix_knowledge_point_id
        ON dbo.q_matrix (knowledge_point_id);
GO
