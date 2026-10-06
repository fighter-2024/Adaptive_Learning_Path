-- 只读验收查询：在目标数据库上下文执行，不包含 INSERT/UPDATE/DELETE/DROP/TRUNCATE。
-- 用于保存空库初始化或增量迁移后的脱敏摘要。

SELECT t.name AS table_name
FROM sys.tables AS t
WHERE t.schema_id = SCHEMA_ID('dbo')
ORDER BY t.name;

SELECT t.name AS table_name, SUM(p.rows) AS row_count
FROM sys.tables AS t
JOIN sys.partitions AS p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
WHERE t.schema_id = SCHEMA_ID('dbo')
GROUP BY t.name
ORDER BY t.name;

SELECT kc.name AS constraint_name, OBJECT_NAME(kc.parent_object_id) AS table_name,
       kc.type_desc AS constraint_type
FROM sys.key_constraints AS kc
WHERE kc.schema_id = SCHEMA_ID('dbo')
ORDER BY table_name, constraint_name;

SELECT cc.name AS constraint_name, OBJECT_NAME(cc.parent_object_id) AS table_name,
       cc.definition
FROM sys.check_constraints AS cc
WHERE OBJECT_SCHEMA_NAME(cc.parent_object_id) = 'dbo'
ORDER BY table_name, constraint_name;

SELECT fk.name AS foreign_key_name,
       OBJECT_NAME(fk.parent_object_id) AS child_table,
       OBJECT_NAME(fk.referenced_object_id) AS parent_table
FROM sys.foreign_keys AS fk
WHERE OBJECT_SCHEMA_NAME(fk.parent_object_id) = 'dbo'
ORDER BY child_table, foreign_key_name;

IF OBJECT_ID('dbo.schema_migrations', 'U') IS NOT NULL
BEGIN
    SELECT version, applied_at
    FROM dbo.schema_migrations
    ORDER BY version;
END
ELSE
BEGIN
    SELECT CAST(NULL AS VARCHAR(32)) AS version,
           CAST(NULL AS DATETIME2) AS applied_at
    WHERE 1 = 0;
END;

-- 迁移失败回滚证据：查询失败版本不存在，而不是修改该表制造结果。
