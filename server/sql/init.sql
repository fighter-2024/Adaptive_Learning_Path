-- ============================================================================
-- 基于知识图谱的自适应学习路径规划与社交激励系统
-- 数据库初始化脚本 (SQL Server)
-- 
-- 生成依据: docs/数据库设计.md
-- 包含 11 张业务表 + 索引 + 唯一约束 + 外键关系注释 + 示例数据
--
-- 注意：本脚本示例数据仅用于结构与接口示意（ch_01=一元二次方程 等），
-- 与 kg-data/data/knowledge_points/*.csv 的演示图谱不是同一套数据
-- （其 ch_01=一元一次方程）。q_matrix / user_kp_mastery 的
-- knowledge_point_id 需与 Neo4j 实际节点 ID 一致（跨库关联，无物理外键）。
-- ============================================================================

-- 这是一次性空库初始化脚本，不是增量升级脚本。
-- 为避免误把已有数据库当成空库而删除数据，发现任一业务表已存在时立即终止。
-- 已有数据库请使用 server/sql/migrate.py 执行版本化迁移。
IF EXISTS (
    SELECT 1
    FROM sys.tables
    WHERE schema_id = SCHEMA_ID('dbo')
      AND name IN (
          'users', 'chapters', 'questions', 'q_matrix', 'answer_records',
          'diagnosis_sessions', 'user_kp_mastery', 'check_ins',
          'achievements', 'user_achievements', 'weekly_reports'
      )
)
    THROW 51000, '目标数据库不是空库；请使用 server/sql/migrate.py，init.sql 不会升级已有数据。', 1;
GO

-- 如需创建数据库，请由 DBA 在目标环境显式执行 CREATE DATABASE；本文件不删除数据库。
-- 数据库创建和切换由 DBA/部署脚本显式完成。

-- ============================================================================
-- 1. users — 用户表
-- 职责：存储学生和管理员的账户信息
-- ============================================================================
CREATE TABLE dbo.users (
    id              INT IDENTITY(1,1)   NOT NULL,
    user_id         VARCHAR(32)         NOT NULL,   -- 业务 ID，如 stu_001 / adm_001
    username        VARCHAR(50)         NOT NULL,   -- 登录账号
    password_hash   VARCHAR(255)        NOT NULL,   -- bcrypt 哈希
    name            NVARCHAR(50)        NOT NULL,   -- 显示名称
    role            VARCHAR(10)         NOT NULL,   -- student / admin
    avatar          VARCHAR(255)        NULL,       -- 头像 URL
    created_at      DATETIME            NOT NULL DEFAULT GETDATE(),
    last_login_at   DATETIME            NULL,
    is_active       BIT                 NOT NULL DEFAULT 1,

    CONSTRAINT PK_users PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_users_user_id UNIQUE (user_id),
    CONSTRAINT UQ_users_username UNIQUE (username),
    CONSTRAINT CK_users_role CHECK (role IN ('student', 'admin'))
);
GO

-- 示例数据
INSERT INTO dbo.users (user_id, username, password_hash, name, role, avatar)
VALUES
    ('stu_001', 'zhangsan',   '$2b$12$dummy_hash_001', N'张三',   'student', NULL),
    ('stu_002', 'lisi',       '$2b$12$dummy_hash_002', N'李四',   'student', NULL),
    ('adm_001', 'admin_wang', '$2b$12$dummy_hash_003', N'王管理', 'admin',  NULL);
GO


-- ============================================================================
-- 2. chapters — 章节表
-- 职责：组织知识的章节结构，支持多级父子关系
-- 外键：parent_chapter_id → chapters.chapter_id（自引用）
-- ============================================================================
CREATE TABLE dbo.chapters (
    id                  INT IDENTITY(1,1)   NOT NULL,
    chapter_id          VARCHAR(32)         NOT NULL,   -- 业务 ID，如 ch_01
    name                NVARCHAR(100)       NOT NULL,   -- 章节名称
    parent_chapter_id   VARCHAR(32)         NULL,       -- 父章节 ID，支持多级
    sort_order          INT                 NOT NULL DEFAULT 0,
    created_at          DATETIME            NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_chapters PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_chapters_chapter_id UNIQUE (chapter_id)
    -- FK: parent_chapter_id → chapters.chapter_id（自引用外键，按需启用）
);
GO

-- 示例数据
INSERT INTO dbo.chapters (chapter_id, name, parent_chapter_id, sort_order)
VALUES
    ('ch_01', N'一元二次方程',    NULL,    1),
    ('ch_02', N'函数与图像',      NULL,    2),
    ('ch_01_01', N'一元二次方程的定义', 'ch_01', 1);
GO


-- ============================================================================
-- 3. questions — 题目表
-- 职责：存储题目题干、选项、答案和解析
-- ============================================================================
CREATE TABLE dbo.questions (
    id              INT IDENTITY(1,1)   NOT NULL,
    question_id     VARCHAR(32)         NOT NULL,   -- 业务 ID，如 q_001
    content         NVARCHAR(2000)      NOT NULL,   -- 题目题干
    type            VARCHAR(20)         NOT NULL,   -- single_choice / multi_choice / true_false
    difficulty      FLOAT               NOT NULL,   -- 0.0 ~ 1.0
    options         NVARCHAR(MAX)       NOT NULL,   -- JSON 数组，如 [{"label":"A","content":"x=2"}]
    answer          VARCHAR(100)        NOT NULL,   -- 正确答案，多选用逗号分隔
    explanation     NVARCHAR(1000)      NULL,       -- 题目解析
    created_at      DATETIME            NOT NULL DEFAULT GETDATE(),
    updated_at      DATETIME            NULL,
    is_active       BIT                 NOT NULL DEFAULT 1,

    CONSTRAINT PK_questions PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_questions_question_id UNIQUE (question_id),
    CONSTRAINT CK_questions_type CHECK (type IN ('single_choice', 'multi_choice', 'true_false')),
    CONSTRAINT CK_questions_difficulty CHECK (difficulty >= 0.0 AND difficulty <= 1.0)
);
GO

-- 示例数据
INSERT INTO dbo.questions (question_id, content, type, difficulty, options, answer, explanation)
VALUES
    ('q_001', N'一元二次方程 x² + 5x + 6 = 0 的解是？',
     'single_choice', 0.3,
     N'[{"label":"A","content":"x=-2或x=-3"},{"label":"B","content":"x=2或x=3"},{"label":"C","content":"x=1或x=6"},{"label":"D","content":"x=-1或x=-6"}]',
     'A', N'因式分解：(x+2)(x+3)=0，解得 x=-2 或 x=-3'),
    ('q_002', N'下列哪些是一元二次方程？（多选）',
     'multi_choice', 0.4,
     N'[{"label":"A","content":"x²+1=0"},{"label":"B","content":"x+2=0"},{"label":"C","content":"x²-3x=0"},{"label":"D","content":"x³-1=0"}]',
     'A,C', N'一元二次方程形如 ax²+bx+c=0 (a≠0)，B 是一元一次，D 是一元三次'),
    ('q_003', N'方程 x² = 4 的解是 x = ±2。',
     'true_false', 0.2,
     N'[{"label":"对","content":"正确"},{"label":"错","content":"错误"}]',
     'true', N'x²=4，开方得 x=±2，正确');
GO


-- ============================================================================
-- 4. q_matrix — Q 矩阵（题目-知识点关联）
-- 职责：记录每道题目考察了哪些知识点，是 DINA 模型的输入
-- 外键：question_id → questions.question_id
--       knowledge_point_id 对应 Neo4j 中的 KnowledgePoint.id
-- ============================================================================
CREATE TABLE dbo.q_matrix (
    id                  INT IDENTITY(1,1)   NOT NULL,
    question_id         VARCHAR(32)         NOT NULL,   -- 题目 ID
    knowledge_point_id  VARCHAR(32)         NOT NULL,   -- 知识点 ID（对应 Neo4j 节点 ID）
    created_at          DATETIME            NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_q_matrix PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_q_matrix_question_kp UNIQUE (question_id, knowledge_point_id)
    -- FK: question_id → questions.question_id
    -- FK: knowledge_point_id → Neo4j KnowledgePoint.id（跨数据库关联，不入物理外键）
);
GO

-- 示例数据
INSERT INTO dbo.q_matrix (question_id, knowledge_point_id)
VALUES
    ('q_001', 'kp_001'),   -- q_001 考察 kp_001（一元二次方程的定义）
    ('q_001', 'kp_002'),   -- q_001 也考察 kp_002（因式分解法）
    ('q_002', 'kp_001');
GO


-- ============================================================================
-- 5. answer_records — 答题记录表
-- 职责：记录学生每次答题的详细信息，是 DINA 模型的数据来源
-- 外键：user_id → users.user_id
--       question_id → questions.question_id
-- ============================================================================
CREATE TABLE dbo.answer_records (
    id              BIGINT IDENTITY(1,1)    NOT NULL,
    record_id       VARCHAR(32)             NOT NULL,   -- 业务 ID，如 ar_001
    user_id         VARCHAR(32)             NOT NULL,   -- 学生 ID
    question_id     VARCHAR(32)             NOT NULL,   -- 题目 ID
    student_answer  VARCHAR(100)            NOT NULL,   -- 学生提交的答案
    is_correct      BIT                     NOT NULL,   -- 是否正确
    time_spent      INT                     NULL,       -- 答题耗时（秒）
    created_at      DATETIME                NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_answer_records PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_answer_records_record_id UNIQUE (record_id)
    -- FK: user_id → users.user_id
    -- FK: question_id → questions.question_id
);
GO

-- 索引：(user_id, created_at)、(question_id)
CREATE NONCLUSTERED INDEX IX_answer_records_user_created
    ON dbo.answer_records (user_id, created_at);
CREATE NONCLUSTERED INDEX IX_answer_records_question_id
    ON dbo.answer_records (question_id);
GO

-- 示例数据
INSERT INTO dbo.answer_records (record_id, user_id, question_id, student_answer, is_correct, time_spent)
VALUES
    ('ar_001', 'stu_001', 'q_001', 'A', 1, 45),
    ('ar_002', 'stu_001', 'q_002', 'A,C', 1, 80),
    ('ar_003', 'stu_002', 'q_001', 'B', 0, 60);
GO


-- ============================================================================
-- 6. diagnosis_sessions — 诊断会话表
-- 职责：保存每次 DINA 诊断的结果快照，追踪学生进步轨迹
-- 外键：user_id → users.user_id
-- ============================================================================
CREATE TABLE dbo.diagnosis_sessions (
    id              INT IDENTITY(1,1)   NOT NULL,
    session_id      VARCHAR(32)         NOT NULL,   -- 业务 ID，如 diag_001
    user_id         VARCHAR(32)         NOT NULL,   -- 学生 ID
    alpha_vector    NVARCHAR(MAX)       NOT NULL,   -- JSON，如 {"kp_001":0.92,"kp_002":0.78}
    question_count  INT                 NOT NULL,   -- 用于本次诊断的答题数
    diagnosed_at    DATETIME            NOT NULL DEFAULT GETDATE(),
    algorithm_version VARCHAR(32)       NOT NULL DEFAULT 'dina-v1',
    parameter_version VARCHAR(32)       NOT NULL DEFAULT 'default-v1',
    answer_time_from DATETIME           NULL,
    answer_time_to   DATETIME           NULL,
    repeat_strategy  VARCHAR(32)        NOT NULL DEFAULT 'latest_attempt',
    converged        BIT                 NOT NULL DEFAULT 0,
    iterations       INT                 NOT NULL DEFAULT 0,

    CONSTRAINT PK_diagnosis_sessions PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_diagnosis_sessions_session_id UNIQUE (session_id)
    -- FK: user_id → users.user_id
);
GO

-- 索引：(user_id, diagnosed_at DESC)
CREATE NONCLUSTERED INDEX IX_diagnosis_sessions_user_diag
    ON dbo.diagnosis_sessions (user_id, diagnosed_at DESC);
GO

-- 示例数据
INSERT INTO dbo.diagnosis_sessions (session_id, user_id, alpha_vector, question_count, diagnosed_at)
VALUES
    ('diag_001', 'stu_001', N'{"kp_001":0.85,"kp_002":0.72,"kp_003":0.45}', 20, '2026-07-01 10:00:00'),
    ('diag_002', 'stu_001', N'{"kp_001":0.92,"kp_002":0.78,"kp_003":0.55}', 25, '2026-07-08 10:00:00'),
    ('diag_003', 'stu_002', N'{"kp_001":0.40,"kp_002":0.35}',              15, '2026-07-01 14:00:00');
GO


-- ============================================================================
-- 7. user_kp_mastery — 用户知识点掌握快照
-- 职责：实时反映每位学生对每个知识点的当前掌握概率，每次答题后更新
-- 外键：user_id → users.user_id
--       knowledge_point_id 对应 Neo4j KnowledgePoint.id
-- ============================================================================
CREATE TABLE dbo.user_kp_mastery (
    id                  INT IDENTITY(1,1)   NOT NULL,
    user_id             VARCHAR(32)         NOT NULL,
    knowledge_point_id  VARCHAR(32)         NOT NULL,   -- 知识点 ID
    mastery_probability FLOAT               NOT NULL,   -- 当前掌握概率
    questions_done      INT                 NOT NULL DEFAULT 0,   -- 该知识点已做题数
    correct_count       INT                 NOT NULL DEFAULT 0,   -- 正确数
    updated_at          DATETIME            NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_user_kp_mastery PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_user_kp_mastery_user_kp UNIQUE (user_id, knowledge_point_id)
    -- FK: user_id → users.user_id
    -- FK: knowledge_point_id → Neo4j KnowledgePoint.id（跨数据库关联）
);
GO

-- 示例数据
INSERT INTO dbo.user_kp_mastery (user_id, knowledge_point_id, mastery_probability, questions_done, correct_count, updated_at)
VALUES
    ('stu_001', 'kp_001', 0.92, 10, 9,  '2026-07-08 10:05:00'),
    ('stu_001', 'kp_002', 0.78, 8,  6,  '2026-07-08 10:05:00'),
    ('stu_002', 'kp_001', 0.40, 5,  2,  '2026-07-01 14:05:00');
GO


-- ============================================================================
-- 8. check_ins — 打卡记录表
-- 职责：记录学生每日打卡信息，支持连续打卡天数追踪
-- 外键：user_id → users.user_id
-- ============================================================================
CREATE TABLE dbo.check_ins (
    id              INT IDENTITY(1,1)   NOT NULL,
    user_id         VARCHAR(32)         NOT NULL,
    check_in_date   DATE                NOT NULL,   -- 打卡日期
    streak_days     INT                 NOT NULL,   -- 当天打卡后的连续天数
    created_at      DATETIME            NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_check_ins PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_check_ins_user_date UNIQUE (user_id, check_in_date)
    -- FK: user_id → users.user_id
);
GO

-- 示例数据
INSERT INTO dbo.check_ins (user_id, check_in_date, streak_days)
VALUES
    ('stu_001', '2026-07-01', 1),
    ('stu_001', '2026-07-02', 2),
    ('stu_002', '2026-07-01', 1);
GO


-- ============================================================================
-- 9. achievements — 成就定义表
-- 职责：定义系统所有可解锁的成就及其触发条件
-- ============================================================================
CREATE TABLE dbo.achievements (
    id              INT IDENTITY(1,1)   NOT NULL,
    achievement_id  VARCHAR(32)         NOT NULL,   -- 业务 ID，如 ach_001
    name            NVARCHAR(50)        NOT NULL,   -- 成就名称
    description     NVARCHAR(200)       NOT NULL,   -- 成就描述
    icon            VARCHAR(50)         NULL,       -- 图标标识
    condition_type  VARCHAR(30)         NOT NULL,   -- first_diagnosis / kp_mastered_count / streak_days / questions_count
    condition_value INT                 NOT NULL,   -- 触发阈值
    created_at      DATETIME            NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_achievements PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_achievements_achievement_id UNIQUE (achievement_id),
    CONSTRAINT CK_achievements_condition_type
        CHECK (condition_type IN ('first_diagnosis', 'kp_mastered_count', 'streak_days', 'questions_count'))
);
GO

-- 示例数据（icon 取值与 docs/API契约文档.md 1.4 的示例风格一致：star/trophy 等）
INSERT INTO dbo.achievements (achievement_id, name, description, icon, condition_type, condition_value)
VALUES
    ('ach_001', N'初次诊断',   N'完成第一次 DINA 认知诊断',        'star',           'first_diagnosis',    1),
    ('ach_002', N'知识猎手',   N'掌握 10 个知识点',               'trophy',         'kp_mastered_count', 10),
    ('ach_003', N'连续打卡 7 天', N'连续打卡满 7 天',             'streak',         'streak_days',        7),
    ('ach_004', N'刷题达人',   N'累计完成 100 道题目',            'questions',      'questions_count',  100);
GO


-- ============================================================================
-- 10. user_achievements — 用户成就记录
-- 职责：记录用户解锁了哪些成就及解锁时间
-- 外键：user_id → users.user_id
--       achievement_id → achievements.achievement_id
-- ============================================================================
CREATE TABLE dbo.user_achievements (
    id              INT IDENTITY(1,1)   NOT NULL,
    user_id         VARCHAR(32)         NOT NULL,
    achievement_id  VARCHAR(32)         NOT NULL,
    unlocked_at     DATETIME            NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_user_achievements PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_user_achievements_user_ach UNIQUE (user_id, achievement_id)
    -- FK: user_id → users.user_id
    -- FK: achievement_id → achievements.achievement_id
);
GO

-- 示例数据
INSERT INTO dbo.user_achievements (user_id, achievement_id, unlocked_at)
VALUES
    ('stu_001', 'ach_001', '2026-07-01 10:30:00'),
    ('stu_001', 'ach_003', '2026-07-07 08:00:00'),
    ('stu_002', 'ach_001', '2026-07-01 14:30:00');
GO


-- ============================================================================
-- 11. weekly_reports — 周报表
-- 职责：存储 AI 生成的每周学习总结报告
-- 外键：user_id → users.user_id
-- ============================================================================
CREATE TABLE dbo.weekly_reports (
    id                  INT IDENTITY(1,1)   NOT NULL,
    report_id           VARCHAR(32)         NOT NULL,   -- 业务 ID，如 wr_001
    user_id             VARCHAR(32)         NOT NULL,
    week_start          DATE                NOT NULL,   -- 周一日期
    week_end            DATE                NOT NULL,   -- 周日日期
    questions_done      INT                 NOT NULL,
    correct_rate        FLOAT               NOT NULL,
    study_time_minutes  INT                 NOT NULL,
    new_mastered        NVARCHAR(MAX)       NULL,       -- JSON 数组，知识点 ID 列表
    still_weak          NVARCHAR(MAX)       NULL,       -- JSON 数组
    ai_summary          NVARCHAR(2000)      NULL,       -- AI 生成的总结文本
    generated_at        DATETIME            NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_weekly_reports PRIMARY KEY CLUSTERED (id),
    CONSTRAINT UQ_weekly_reports_report_id UNIQUE (report_id),
    CONSTRAINT UQ_weekly_reports_user_week UNIQUE (user_id, week_start),
    CONSTRAINT CK_weekly_reports_correct_rate CHECK (correct_rate >= 0.0 AND correct_rate <= 1.0)
    -- FK: user_id → users.user_id
);
GO

-- 示例数据
INSERT INTO dbo.weekly_reports (
    report_id, user_id, week_start, week_end,
    questions_done, correct_rate, study_time_minutes,
    new_mastered, still_weak, ai_summary
)
VALUES
    ('wr_001', 'stu_001', '2026-06-29', '2026-07-05',
     35, 0.83, 120,
     N'["kp_001","kp_002"]', N'["kp_003"]',
     N'本周你在"一元二次方程的定义"和"因式分解法"上表现优异，掌握概率均超过 0.8。建议下周重点突破"求根公式法"。'),
    ('wr_002', 'stu_002', '2026-06-29', '2026-07-05',
     18, 0.56, 60,
     N'["kp_001"]', N'["kp_002","kp_003"]',
     N'本周你初步掌握了"一元二次方程的定义"，但在"因式分解法"和"求根公式法"上仍需加强练习。');
GO


-- ============================================================================
-- 汇总：外键关系一览（均以注释标注，不创建物理外键约束）
-- ============================================================================
/*
| 子表                   | 子表列               | → 父表                  | 父表列              |
|------------------------|----------------------|------------------------|---------------------|
| chapters               | parent_chapter_id    | → chapters             | chapter_id          |
| q_matrix               | question_id          | → questions            | question_id         |
| answer_records         | user_id              | → users                | user_id             |
| answer_records         | question_id          | → questions            | question_id         |
| diagnosis_sessions     | user_id              | → users                | user_id             |
| user_kp_mastery        | user_id              | → users                | user_id             |
| check_ins              | user_id              | → users                | user_id             |
| user_achievements      | user_id              | → users                | user_id             |
| user_achievements      | achievement_id       | → achievements         | achievement_id      |
| weekly_reports         | user_id              | → users                | user_id             |

跨数据库关联（SQL Server ↔ Neo4j）：
| 子表                   | 子表列               | → Neo4j 节点           | 属性                |
|------------------------|----------------------|------------------------|---------------------|
| q_matrix               | knowledge_point_id   | → KnowledgePoint       | id                  |
| user_kp_mastery        | knowledge_point_id   | → KnowledgePoint       | id                  |
*/

PRINT '数据库初始化完成。共创建 11 张表，已插入示例数据。';
GO
