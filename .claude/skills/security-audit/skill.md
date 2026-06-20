---
name: security-audit
version: 1.0
description: 对指定代码进行安全审计，依据 OWASP Top 10 和团队安全规范输出审计报告
trigger: ["安全审计", "security audit", "安全检查", "代码安全"]
---

# 代码安全审计

## 执行步骤

1. 读取用户指定的代码文件或目录
2. 阅读 `references/owasp-top10-checklist.md`，逐项检查代码是否存在对应漏洞
3. 阅读 `references/team-security-standards.md`，检查代码是否符合团队安全规范
4. 按照 `resources/examples/audit-report-sample.md` 的格式，生成安全审计报告
5. 对每个发现的问题：标注严重等级（高危/中危/低危）、给出修复建议和修复代码

## 输出规范
- 使用 Markdown 表格列出所有问题
- 每个问题包含：文件路径、行号、问题描述、严重等级、修复建议
- 最后给出安全评分（0-100）和总结

## 错误处理
- 如果代码量过大，优先审计 API 路由和数据库操作相关的文件
- 如果无法判断是否存在风险，标记为"待人工确认"