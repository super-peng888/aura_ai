-- ============================================
-- 菜单迁移：配置中心（父菜单）+ 模型配置/解析策略/检索配置（子菜单）
-- 幂等，可重复执行
-- ============================================

-- 1. 新增「配置中心」父菜单与「模型配置」子菜单
INSERT INTO permissions (id, code, name, type, path, icon, parent_id, sort_order, hidden) VALUES
    ('menu-config-center', 'menu-config-center', '配置中心', 'menu', NULL, 'Settings', NULL, 15, FALSE),
    ('menu-model-config', 'menu-model-config', '模型配置', 'menu', '/model-config', 'Bot', 'menu-config-center', 1, FALSE)
ON CONFLICT (code) DO NOTHING;

-- 2. 既有菜单挂到配置中心下（幂等 UPDATE）
UPDATE permissions SET parent_id = 'menu-config-center', sort_order = 2 WHERE code = 'parse_strategies';
UPDATE permissions SET parent_id = 'menu-config-center', sort_order = 3 WHERE code = 'menu-retrieval-config';

-- 3. admin 角色授权（全部权限，含新菜单；配置中心菜单不进 user 白名单）
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;
